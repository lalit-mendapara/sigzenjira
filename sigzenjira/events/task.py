import json
from html import unescape

import frappe
from frappe import _
from frappe.desk.form import assign_to
from frappe.model.naming import make_autoname
from frappe.utils import cint, flt, get_link_to_form, getdate, strip_html_tags

from sigzenjira.permission.project_user import user_has_project_flag

WORK_ITEM_TYPE_NAME_PREFIX = {
	"Epic": "E",
	"Story": "S",
	"Task": "T",
	"Sub-task": "ST",
}


def autoname(doc, method):
	# The name spells out the whole lineage, so any leaf points back at its root
	# without a lookup: E-001 / E-001-S-001 / E-001-S-001-T-001 / ...-ST-001.
	# The counter is per-parent because frappe's Series table is keyed on the
	# literal prefix - "E-001-S-001-T-" gets its own row, so each parent's
	# children number from 001 independently.
	# A standalone Story/Task (OPTIONAL_PARENT_TYPES) has no parent to prefix
	# with, so it falls back to a global counter for its own type.
	prefix = WORK_ITEM_TYPE_NAME_PREFIX.get(doc.custom_task_work_item_type, "T")
	base = f"{doc.parent_task}-{prefix}-" if doc.parent_task else f"{prefix}-"
	# ponytail: the name records where the item was CREATED, not where it lives
	# now - reparenting deliberately does not rename (a cascade rename would
	# invalidate every reference already pasted into a mail/ticket, which is the
	# exact thing this naming scheme exists to make durable).
	# ponytail: 999 siblings per parent; widen to .#### if any parent gets close.
	doc.name = make_autoname(base + ".###")


EXPECTED_PARENT_TYPE = {
	"Epic": None,
	"Story": "Epic",
	"Task": "Story",
	"Sub-task": "Task",
}

# Only these two levels have their expected_time checked against a parent's
# budget. Epic is the top of the tree (nothing above it to check against);
# Sub-task is excluded by spec.
BUDGET_CHECKED_TYPES = {"Story", "Task"}

# Story and Task may stand alone (no Epic / no Story) when the user doesn't
# want that level of grouping. Epic never has a parent; Sub-task always needs
# a Task parent — those two stay hard requirements.
OPTIONAL_PARENT_TYPES = {"Story", "Task"}


def mark_parent_as_group(doc, method):
	# Core ERPNext's Task tree (NestedSet) refuses to nest under a task that
	# isn't flagged is_group, and checks that on the CHILD's own validate()
	# before any of our doc_events hooks run — so this has to happen in
	# before_validate, one step earlier, or the core check throws first.
	# is_group starts unchecked and only flips on once a real child shows up;
	# it isn't forced on just because a task's type could theoretically have
	# children (an empty Story/Task shows as not-a-group until it actually is one).
	if doc.parent_task and not frappe.db.get_value("Task", doc.parent_task, "is_group"):
		frappe.db.set_value("Task", doc.parent_task, "is_group", 1)


WORK_ITEM_TYPE_PRIVILEGED_ROLES = {"Director", "Product Owner", "Projects Manager", "System Manager"}


def validate_work_item_type_permission(doc, method):
	# Only these roles - or a Project User explicitly granted "Set Work Item
	# Type" on this Task's Project - may classify a Task as Epic/Story/Task;
	# everyone else (Employee) is restricted to Sub-task, per the org's
	# approval hierarchy. Checked against the previous saved value (like
	# validate_expected_time_edit_permission below) so an Employee can still
	# save OTHER edits (status, progress) on an existing higher-level item
	# without this rule getting in the way - it only fires when they
	# actually try to set/change the classification itself.
	if doc.flags.via_issue_mapping:
		# Classification was set by make_story(), not chosen by the user -
		# the manual Director/PO/Projects Manager gate doesn't apply here.
		return

	if WORK_ITEM_TYPE_PRIVILEGED_ROLES & set(frappe.get_roles(frappe.session.user)):
		return

	# Per-Project grant, so a Projects Manager can hand this out to one
	# Project's members without giving anyone an org-wide role. A Task with no
	# Project can't match a Project User row, so it stays role-only.
	if user_has_project_flag(doc.project, "custom_project_user_set_work_item_type"):
		return

	previous_value = None if doc.is_new() else (doc.get_doc_before_save() or {}).get("custom_task_work_item_type")
	if doc.custom_task_work_item_type == previous_value:
		return

	if doc.custom_task_work_item_type != "Sub-task":
		frappe.throw(
			_(
				"Only a Director, Product Owner, or Projects Manager - or a Project User granted Set Work Item Type on this Project - can set Work Item Type to {0}. You can only create a Sub-task."
			).format(doc.custom_task_work_item_type)
		)


def validate_hierarchy(doc, method):
	expected_parent_type = EXPECTED_PARENT_TYPE.get(doc.custom_task_work_item_type)

	if expected_parent_type is None:
		if doc.parent_task:
			frappe.throw(_("An Epic cannot have a parent task."))
		return

	if not doc.parent_task:
		if doc.custom_task_work_item_type in OPTIONAL_PARENT_TYPES:
			return
		frappe.throw(
			_("A {0} must have a parent task of type {1}.").format(
				doc.custom_task_work_item_type, expected_parent_type
			)
		)

	parent_work_item_type = frappe.db.get_value("Task", doc.parent_task, "custom_task_work_item_type")
	if parent_work_item_type != expected_parent_type:
		frappe.throw(
			_("A {0}'s parent task {1} must be of type {2}, not {3}.").format(
				doc.custom_task_work_item_type,
				get_link_to_form("Task", doc.parent_task),
				expected_parent_type,
				parent_work_item_type or _("unset"),
			)
		)


def validate_parent_task_is_immutable(doc, method):
	# The parent a work item is born under is baked into its name (autoname) and
	# into every hour rollup above it, so moving it later leaves a name pointing
	# at a branch it no longer sits on. Attaching a standalone Story/Task to a
	# parent later is still allowed - only overwriting or clearing a parent that
	# is already set is refused, for everyone, no role bypass.
	if doc.is_new():
		return

	previous_parent = (doc.get_doc_before_save() or {}).get("parent_task")
	if previous_parent and doc.parent_task != previous_parent:
		frappe.throw(
			_("Parent Task cannot be changed once set - {0} stays under {1}.").format(
				doc.name, get_link_to_form("Task", previous_parent)
			)
		)


def _manual_task_under_story(doc):
	# A Task that landed under a Story from somewhere other than the split
	# grid - the Task form, the list view, the Work Board, the API. Returns the
	# Story it belongs to, or None if this isn't that case.
	if doc.custom_task_work_item_type != "Task" or not doc.parent_task:
		return None

	if frappe.db.get_value("Task", doc.parent_task, "custom_task_work_item_type") != "Story":
		return None

	if frappe.db.exists("Task Split", {"parent": doc.parent_task, "generated_task": doc.name}):
		return None

	# The split path inserts its Task BEFORE writing generated_task back onto
	# the row, so during that window the only proof the Task already has a row
	# is the is_generating claim generate_tasks_from_split stakes first. Only
	# a row still IN that window counts - is_generating is never cleared once
	# set, so an already-linked row would otherwise mask every later Task.
	if frappe.db.exists(
		"Task Split",
		{"parent": doc.parent_task, "is_generating": 1, "generated_task": ["in", ("", None)]},
	):
		return None

	return doc.parent_task


def create_split_row_for_manual_task(doc, method):
	# A Task created outside the grid - the Task form's "Create Task" button,
	# the list view, the Work Board, the API - gets a row of its own rather
	# than being refused: a Task with no row is invisible to
	# rollup_story_expected_time (which derives the Story's total from the rows
	# alone) while still counting against it in validate_hour_budget.
	#
	# This used to be refused outright for the FIRST Task under a Story, on the
	# grounds that the mirrored row would drag a hand-declared expected_time
	# down to itself. It no longer can: a hand-typed budget sets
	# custom_task_story_budget_is_manual, and rollup_story_expected_time only
	# overwrites expected_time while that flag is 0.
	story_name = _manual_task_under_story(doc)
	if not story_name:
		return

	# Saved through the Story doc, not a raw insert: the row has to go past
	# rollup_story_expected_time (so the Story's total picks the hours up, or
	# refuses them if they'd breach a pinned budget) and past
	# validate_task_split_expected_hours_permission - adding a Task under a
	# Story is allocating hours to it, whichever form it's typed into.
	story = frappe.get_doc("Task", story_name)
	story.append(
		"custom_task_task_split",
		{
			"task_item": doc.subject,
			# Task.description is a Text Editor (HTML), the row's is Small Text -
			# handing the markup over unchanged shows the user raw
			# <div class="ql-editor"> soup in the grid.
			"description": unescape(strip_html_tags(doc.description or "")).strip(),
			"expected_hours": flt(doc.expected_time),
			"ecd": doc.exp_end_date,
			"is_billable": cint(doc.custom_task_is_billable),
			"generated_task": doc.name,
		},
	)
	story.save()


EXPECTED_TIME_RESTRICTED_TYPES = {"Epic"}
EXPECTED_TIME_PRIVILEGED_ROLES = {"Projects Manager", "System Manager"}


def validate_expected_time_edit_permission(doc, method):
	# Epic's budget is a planning decision, not something a developer
	# estimating their own Tasks should be able to move. Story is excluded
	# here on purpose: rollup_story_expected_time below now derives it from
	# custom_task_task_split, so whoever fills that table (per spec, not
	# necessarily a Projects Manager) drives the number - see
	# validate_hour_budget for why Task/Sub-task's expected_time stays open.
	if doc.custom_task_work_item_type not in EXPECTED_TIME_RESTRICTED_TYPES:
		return

	if EXPECTED_TIME_PRIVILEGED_ROLES & set(frappe.get_roles(frappe.session.user)):
		return

	previous_expected_time = (
		0 if doc.is_new() else flt((doc.get_doc_before_save() or {}).get("expected_time"))
	)
	if flt(doc.expected_time) != previous_expected_time:
		frappe.throw(_("Only a Projects Manager can set or change Expected Time on an Epic."))


def sync_actual_extra_hours(doc, method):
	# recompute_actual_time (events/timesheet.py) covers the Timesheet-driven
	# path via a raw db.set_value that bypasses validate(); this covers a plain
	# doc.save() that only changes expected_time. Overrun only - under budget
	# reads as 0, never negative.
	doc.custom_task_actual_extra_hours = max(flt(doc.actual_time) - flt(doc.expected_time), 0)


def validate_task_split_expected_hours_permission(doc, method):
	# Expected Hours is the budget commitment on a split row - only a Project
	# User flagged custom_project_user_allocate_hours (or Administrator/System Manager,
	# via user_has_project_flag) for this Task's project may set or change it.
	# Re-checked here since the Desk grid (task.js) only makes the column
	# read-only client-side, not real enforcement against direct API calls.
	if doc.custom_task_work_item_type != "Story":
		return

	if user_has_project_flag(doc.project, "custom_project_user_allocate_hours"):
		return

	before = doc.get_doc_before_save()
	before_rows = {row.name: flt(row.expected_hours) for row in (before.custom_task_task_split if before else [])}

	for row in doc.get("custom_task_task_split") or []:
		previous_hours = before_rows.get(row.name, 0)
		if flt(row.expected_hours) != previous_hours:
			frappe.throw(
				_(
					"Only a user with Allocate Hours access on this Project can set Expected Hours on the Task Split table."
				)
			)


def validate_task_split_assign_permission(doc, method):
	# Assign is the other budget-adjacent commitment on a split row - only a
	# Project User flagged custom_project_user_assign_users (or Administrator/System
	# Manager, via user_has_project_flag) for this Task's project may stage
	# assignees on a not-yet-generated row. Re-checked here since the Desk
	# grid's Assign dialog (task.js) only hides/disables client-side, not
	# real enforcement against direct API calls. The generated_task case is
	# gated separately in set_split_row_assignees below.
	if doc.custom_task_work_item_type != "Story":
		return

	if user_has_project_flag(doc.project, "custom_project_user_assign_users"):
		return

	before = doc.get_doc_before_save()
	before_rows = {row.name: row.pending_assign_users for row in (before.custom_task_task_split if before else [])}

	for row in doc.get("custom_task_task_split") or []:
		if row.pending_assign_users != before_rows.get(row.name):
			frappe.throw(
				_(
					"You can only stage assignees on the Task Split table if you have Assign Users access on this Project."
				)
			)


def validate_one_story_per_issue(doc, method):
	# An Issue maps to exactly one live Story - a second make_story() call (or
	# a manually created Story) on the same Issue would leave two Stories
	# both claiming to be "the" story for that Issue.
	if doc.custom_task_work_item_type != "Story" or not doc.issue:
		return

	existing = frappe.db.exists(
		"Task",
		{
			"issue": doc.issue,
			"custom_task_work_item_type": "Story",
			"name": ["!=", doc.name or ""],
			"docstatus": ["!=", 2],
		},
	)
	if existing:
		frappe.throw(
			_("Issue {0} already has a Story: {1}.").format(doc.issue, get_link_to_form("Task", existing))
		)


EMPLOYEE_STORY_LOCKED_EXCEPTIONS = {"custom_task_task_template", "expected_time"}
# expected_time is excepted because rollup_story_expected_time recomputes it
# automatically from custom_task_task_split whenever rows change - it's a derived
# side effect of picking a template, not something the Employee sets directly.


def user_can_manage_story(project):
	# The Story-level gate: a privileged role, or the same per-Project grant
	# that lets this user create a Story here
	# (validate_work_item_type_permission) - without it they could make one and
	# then be locked out of editing it.
	if WORK_ITEM_TYPE_PRIVILEGED_ROLES & set(frappe.get_roles(frappe.session.user)):
		return True

	return bool(user_has_project_flag(project, "custom_project_user_set_work_item_type"))


def validate_task_split_row_deletion(doc, method):
	# Adding a split row is open to anyone who can edit the Story (an Employee
	# breaking their own work down), but removing one is not: a row deletion
	# cascades into deleting the generated Task and every Sub-task under it
	# (delete_tasks_for_removed_split_rows), which is a plan decision, not a
	# breakdown detail. Server-side because task.js's cannot_delete_rows only
	# hides the button - validate_employee_story_field_restriction skips Table
	# fieldtypes, so nothing else here looks at a row that vanished.
	if doc.is_new() or doc.custom_task_work_item_type != "Story":
		return

	if user_can_manage_story(doc.project):
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	kept = {row.name for row in doc.get("custom_task_task_split") or []}
	if any(row.name not in kept for row in before.get("custom_task_task_split") or []):
		frappe.throw(
			_("You can add rows to the Task Split table, but only a Project Manager can remove one.")
		)


def validate_employee_story_field_restriction(doc, method):
	# A Story always already exists by the time an Employee can reach it
	# (validate_work_item_type_permission keeps them from creating one from
	# scratch) - the one thing they're allowed to do on it is pick a Task
	# Template, plus add rows to the split table (Table fieldtypes are skipped
	# below; removal is gated in validate_task_split_row_deletion). Everything
	# else - subject, priority, dates, status - stays whoever created/owns the
	# Story's call.
	if doc.is_new() or doc.custom_task_work_item_type != "Story":
		return

	if user_can_manage_story(doc.project):
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	for df in doc.meta.fields:
		if df.fieldtype in ("Table", "Section Break", "Column Break", "Tab Break"):
			continue
		if df.fieldname in EMPLOYEE_STORY_LOCKED_EXCEPTIONS:
			continue
		if doc.get(df.fieldname) != before.get(df.fieldname):
			frappe.throw(_("You can only select a Task Template on this Story."))


def rollup_story_expected_time(doc, method):
	# The split table is what a Story's hours normally come from - the PM
	# shouldn't pre-declare a total before splitting, then hope it matches.
	# But a user with Allocate Hours on the Project may hand-set a budget
	# ABOVE the table's total (headroom for work not planned line by line);
	# that pins expected_time (custom_task_story_budget_is_manual) so later saves
	# stop dragging it back down to the rollup. Below the total is never
	# allowed - the budget has to cover the hours already allocated.
	if doc.custom_task_work_item_type != "Story":
		return

	before = doc.get_doc_before_save()
	split_rows = doc.get("custom_task_task_split") or []
	split_total = sum(flt(row.expected_hours) for row in split_rows)
	# Allocated is always estimate + approved extra: an approved Additional
	# Hours Request is as committed against the budget as the original
	# estimate. expected_time itself stays the estimate alone - extra hours
	# have their own rollup in custom_task_extra_hours, and folding them in here
	# would count them twice.
	allocated_total = split_total + sum(flt(row.extra_hours) for row in split_rows)
	previous = 0 if doc.is_new() else flt((before or {}).get("expected_time"))

	if flt(doc.expected_time) == previous:
		# Nobody touched the field this save. A Story's Expected Time is a
		# ceiling, not a running total: the table may fill it but never grow
		# past it. Raising it (the branch below) is the only way to make room,
		# which keeps that decision with whoever holds Allocate Hours instead
		# of leaking it to anyone who can add a row or a Task.
		#
		# Only an INCREASE is blocked: an approved Additional Hours Request
		# writes extra_hours straight to the row (db.set_value, no Story save),
		# so allocation can legitimately already sit above the ceiling -
		# blocking on the state rather than the change would leave that Story
		# unsaveable for good.
		previous_allocated = sum(
			flt(row.expected_hours) + flt(row.extra_hours)
			for row in ((before.custom_task_task_split if before else None) or [])
		)
		if (
			flt(doc.expected_time)
			and allocated_total > flt(doc.expected_time)
			and allocated_total > previous_allocated
		):
			frappe.throw(
				_(
					"Allocated hours would total {0}h, exceeding this Story's Expected Time of {1}h. Raise the Story's Expected Time first."
				).format(allocated_total, flt(doc.expected_time))
			)

		# Nothing declared yet (a fresh Story being split for the first time,
		# or a template being applied): the table sets the opening number.
		# After that the Story only tracks the table DOWNWARD - shrinking the
		# plan never needs anyone's permission, growing it does.
		if split_rows and not cint(doc.custom_task_story_budget_is_manual):
			doc.expected_time = split_total
		return

	# Hand-typed number from here on. Same gate as the split table's Expected
	# Hours column - a Story's budget is an allocation decision.
	if not user_has_project_flag(doc.project, "custom_project_user_allocate_hours"):
		frappe.throw(
			_("Only a user with Allocate Hours access on this Project can change Expected Time on a Story.")
		)

	if flt(doc.expected_time) < allocated_total:
		frappe.throw(_("You can not set expected hour of story less than total hours of allocated tasks."))

	doc.custom_task_story_budget_is_manual = 1 if flt(doc.expected_time) > allocated_total else 0


def delete_tasks_for_removed_split_rows(doc, method):
	# A split row and its generated Task are the same work item seen from two
	# places - dropping the row from the grid has to take the Task with it,
	# otherwise the Story keeps a child that traces back to no plan line.
	# Frappe has already deleted the removed rows from the DB by now, so the
	# pre-save snapshot is the only place their generated_task still exists.
	if doc.custom_task_work_item_type != "Story":
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	kept = {row.name for row in doc.get("custom_task_task_split") or []}
	for old_row in before.get("custom_task_task_split") or []:
		if old_row.name in kept or not old_row.generated_task:
			continue
		if not frappe.db.exists("Task", old_row.generated_task):
			continue
		delete_task_with_sub_tasks(old_row.generated_task)


def delete_task_with_sub_tasks(task_name):
	# A Sub-task is a breakdown of its Task, never a plan line of its own, so
	# it goes when the Task goes - core refuses to delete a Task that still has
	# children, which otherwise left the Task sitting in the list view with its
	# split row already gone.
	#
	# Still not forced, and deliberately so: a Task (or Sub-task) with logged
	# Timesheets stops the whole save with core's own link error. Dropping a
	# plan line that already has real hours against it should fail loudly, not
	# silently take the work with it.
	for sub_task in frappe.get_all("Task", filters={"parent_task": task_name}, pluck="name"):
		delete_task_with_sub_tasks(sub_task)

	frappe.delete_doc("Task", task_name)


# INVARIANT: a raw frappe.db.set_value to a billable flag skips validate(), so
# it bypasses the billable clamp entirely (events/billable.py). The only two
# sanctioned exceptions are the Task Split <-> generated Task mirror: this
# function (row -> Task.custom_task_is_billable) and sync_expected_hours_to_split_row
# below (Task -> row.is_billable). Both are safe only because the doc being
# mirrored FROM was itself clamped on the save that triggered them - and the
# row -> Task direction still needs validate_split_row_unbilling
# (events/billable.py) to stand in for the validate() it skips, because a row
# going 1 -> 0 can strand billable Sub-tasks under the generated Task. Any new
# raw write to either field must name the guard that covers it, or use save().
def sync_split_row_edits_to_generated_task(doc, method):
	# generate_tasks_from_split deliberately ignores edits to an
	# already-generated row's expected_hours (see its own comment) - that
	# only means "don't regenerate the Task", not "don't push the edit
	# through". Without this, editing an already-split row never reaches the
	# Task it created.
	if doc.custom_task_work_item_type != "Story":
		return

	for row in doc.get("custom_task_task_split") or []:
		if not row.generated_task:
			continue
		if flt(row.expected_hours) != flt(frappe.db.get_value("Task", row.generated_task, "expected_time")):
			frappe.db.set_value(
				"Task", row.generated_task, "expected_time", flt(row.expected_hours), update_modified=False
			)

		task_exp_end_date = frappe.db.get_value("Task", row.generated_task, "exp_end_date")
		current_ecd = getdate(task_exp_end_date) if task_exp_end_date else None
		row_ecd = getdate(row.ecd) if row.ecd else None
		if row_ecd != current_ecd:
			frappe.db.set_value("Task", row.generated_task, "exp_end_date", row_ecd, update_modified=False)

		if cint(row.is_billable) != cint(
			frappe.db.get_value("Task", row.generated_task, "custom_task_is_billable")
		):
			frappe.db.set_value(
				"Task", row.generated_task, "custom_task_is_billable", cint(row.is_billable), update_modified=False
			)


def validate_hour_budget(doc, method):
	# A standalone Story/Task (no parent) has no budget to check against.
	if doc.custom_task_work_item_type not in BUDGET_CHECKED_TYPES or not doc.parent_task:
		return

	parent_budget = flt(frappe.db.get_value("Task", doc.parent_task, "expected_time"))
	if not parent_budget:
		# Epic/Story not every time carry a declared budget - nothing to check against.
		return

	sibling_hours = flt(
		frappe.db.sql(
			"""
			select sum(expected_time) from `tabTask`
			where parent_task = %s and custom_task_work_item_type = %s and name != %s
			""",
			(doc.parent_task, doc.custom_task_work_item_type, doc.name or ""),
		)[0][0]
	)

	total_hours = sibling_hours + flt(doc.expected_time)

	if total_hours > parent_budget:
		frappe.throw(
			_("Total {0} hours under parent task {1} would be {2}h, exceeding its budget of {3}h.").format(
				doc.custom_task_work_item_type,
				get_link_to_form("Task", doc.parent_task),
				total_hours,
				parent_budget,
			)
		)


def generate_tasks_from_split(doc, method):
	# Rows with no expected_hours yet are still being filled in (possibly by
	# a different Projects Manager on a later save) - only turn a row into a
	# real Task once it actually has hours, and only once: generated_task
	# marks a row as done, so re-saving the Story never creates duplicates
	# or reacts to edits made to an already-generated row's expected_hours.
	if doc.custom_task_work_item_type != "Story":
		return

	for row in doc.get("custom_task_task_split") or []:
		if not flt(row.expected_hours):
			continue

		# Don't trust row.generated_task/row.is_generating here - they're
		# from the snapshot loaded when THIS invocation started. Core's
		# populate_depends_on recursively re-enters this same function (via
		# parent.save()) for every child Task inserted below, on its own
		# freshly reloaded Story. A nested call can claim and fully generate
		# a LATER row in this same list while THIS loop is still paused
		# mid-iteration on an EARLIER row - so by the time this loop reaches
		# that later row, its in-memory copy is stale even though the DB
		# moved on. Re-check live DB state per row, right before acting.
		live_generated_task, live_is_generating = frappe.db.get_value(
			"Task Split", row.name, ["generated_task", "is_generating"]
		)
		if live_generated_task or live_is_generating:
			continue

		# Claiming the row BEFORE inserting means a recursive re-entry (see
		# above) sees it as already spoken for instead of duplicating it.
		# Can't use generated_task itself for this (it's a Link to Task, and
		# core's parent.save() above fully re-validates the Story, including
		# this Link - a placeholder string there fails link validation).
		frappe.db.set_value("Task Split", row.name, "is_generating", 1)

		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": f"{row.task_item} - {doc.subject}",
				"project": doc.project,
				"parent_task": doc.name,
				"description": row.description,
				"custom_task_work_item_type": "Task",
				"expected_time": row.expected_hours,
				"custom_task_is_billable": row.is_billable,
				"priority": doc.priority,
				"exp_end_date": row.ecd,
			}
		).insert(ignore_permissions=True)

		frappe.db.set_value("Task Split", row.name, "generated_task", task.name)

		# Picks staged before the row generated (task_split.js's Assign
		# dialog, no generated_task yet -> pending_assign_users) become real
		# assignment the moment the Task exists - same Story save, no extra
		# round trip needed.
		for user in json.loads(row.pending_assign_users) if row.pending_assign_users else []:
			assign_to._add(
				{"assign_to": [user], "doctype": "Task", "name": task.name}, ignore_permissions=True
			)
		if row.pending_assign_users:
			frappe.db.set_value("Task Split", row.name, "pending_assign_users", None)


def sync_expected_hours_to_split_row(doc, method):
	# generate_tasks_from_split only writes Task Split.expected_hours once, at
	# creation time - a later edit to the generated Task's own expected_time
	# never makes it back into the split row (or the Story's derived total)
	# without this.
	if doc.custom_task_work_item_type != "Task" or not doc.parent_task:
		return

	split_row = frappe.db.get_value("Task Split", {"generated_task": doc.name}, ["name", "parent"])
	if not split_row:
		return

	row_name, story_name = split_row
	frappe.db.set_value(
		"Task Split",
		row_name,
		{
			"expected_hours": doc.expected_time,
			"ecd": getdate(doc.exp_end_date) if doc.exp_end_date else None,
			"is_billable": cint(doc.custom_task_is_billable),
		},
	)

	sync_story_total_from_split(story_name)


def sync_story_total_from_split(story_name):
	# db-level recompute of a Story's total from its split rows, used by the
	# two paths that edit rows without saving the Story doc. Both must respect
	# a budget pinned above the table by rollup_story_expected_time - only a
	# table that outgrew the pin moves the number.
	story_total = flt(
		frappe.db.sql("select sum(expected_hours) from `tabTask Split` where parent = %s", story_name)[0][0]
	)
	story = frappe.db.get_value(
		"Task", story_name, ["expected_time", "custom_task_story_budget_is_manual"], as_dict=True
	)
	if story and cint(story.custom_task_story_budget_is_manual) and story_total <= flt(story.expected_time):
		return

	frappe.db.set_value(
		"Task",
		story_name,
		{"expected_time": story_total, "custom_task_story_budget_is_manual": 0},
		update_modified=False,
	)


@frappe.whitelist()
def get_task_split_permissions(project=None):
	# Backs the Desk form's client-side locks (task.js) - the Task Split grid's
	# Expected Hours column and Assign action, and the Work Item Type dropdown.
	# Client-side query of the same
	# validate_task_split_expected_hours_permission /
	# validate_task_split_assign_permission / validate_work_item_type_permission
	# gates; those remain the real enforcement.
	return {
		"allocate_hours": user_has_project_flag(project, "custom_project_user_allocate_hours"),
		"assign_users": user_has_project_flag(project, "custom_project_user_assign_users"),
		"set_work_item_type": user_has_project_flag(project, "custom_project_user_set_work_item_type"),
	}


@frappe.whitelist()
def get_project_assignable_users(project=None):
	# Backs the split grid's Assign dialog (task.js) - the picker only ever
	# offers this Project's team, so a row can't be handed to someone with no
	# access to the work. A Task with no Project has no team to scope to, so it
	# falls back to every enabled System User.
	filters = {"enabled": 1, "user_type": "System User"}
	if project:
		filters["name"] = ["in", frappe.get_all("Project User", filters={"parent": project}, pluck="user")]

	return [
		frappe._dict(value=user.name, description=user.full_name)
		for user in frappe.get_all("User", filters=filters, fields=["name", "full_name"], order_by="full_name")
	]


@frappe.whitelist()
def set_split_row_assignees(row_name, users):
	# The grid's Assign button/dialog (task_split.js) is the only write path
	# for a row's assignment - real user action, so ignore_permissions=False
	# (unlike the background sync hooks above, which run as the system).
	users = set(frappe.parse_json(users))
	generated_task = frappe.db.get_value("Task Split", row_name, "generated_task")
	if not generated_task:
		frappe.throw(_("This row hasn't generated a Task yet."))

	story_name = frappe.db.get_value("Task Split", row_name, "parent")
	project = frappe.db.get_value("Task", story_name, "project")
	if not user_has_project_flag(project, "custom_project_user_assign_users"):
		frappe.throw(_("You dont have permission to assign users from task-split "))

	raw_assign = frappe.db.get_value("Task", generated_task, "_assign")
	current_users = set(json.loads(raw_assign) if raw_assign else [])

	for user in users - current_users:
		assign_to.add({"assign_to": [user], "doctype": "Task", "name": generated_task})

	for user in current_users - users:
		assign_to.remove("Task", generated_task, user)


@frappe.whitelist()
def create_task_without_hours(row_name):
	# generate_tasks_from_split only turns a row into a real Task once
	# expected_hours is filled in - this is the escape hatch for a PM who
	# wants the Task to exist (so it can be assigned/worked on) before the
	# hour budget for it is known yet.
	row = frappe.db.get_value(
		"Task Split",
		row_name,
		[
			"parent",
			"task_item",
			"description",
			"ecd",
			"generated_task",
			"is_generating",
			"pending_assign_users",
			"is_billable",
		],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Task Split row not found."))
	if row.generated_task or row.is_generating:
		frappe.throw(_("This row has already generated a Task."))

	story = frappe.get_doc("Task", row.parent)
	if not (
		user_has_project_flag(story.project, "custom_project_user_allocate_hours")
		or user_has_project_flag(story.project, "custom_project_user_set_work_item_type")
	):
		frappe.throw(
			_(
				"Only a user with Allocate Hours or Set Work Item Type access on this Project can create a Task from this row."
			)
		)

	frappe.db.set_value("Task Split", row_name, "is_generating", 1)

	task = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": f"{row.task_item} - {story.subject}",
			"project": story.project,
			"parent_task": story.name,
			"description": row.description,
			"custom_task_work_item_type": "Task",
			"priority": story.priority,
			"exp_end_date": row.ecd,
			"custom_task_is_billable": row.is_billable,
		}
	)
	task.insert()

	frappe.db.set_value("Task Split", row_name, "generated_task", task.name)

	for user in json.loads(row.pending_assign_users) if row.pending_assign_users else []:
		assign_to.add({"assign_to": [user], "doctype": "Task", "name": task.name})
	if row.pending_assign_users:
		frappe.db.set_value("Task Split", row_name, "pending_assign_users", None)

	return task.name


def cleanup_task_references_on_delete(doc, method):
	# Deleting a Task leaves two kinds of dangling reference otherwise:
	# - a "Task Depends On" row on whichever Task it's linked from (core's
	#   populate_depends_on auto-adds one on the parent when a child Task is
	#   created, but nothing removes it when the child is deleted).
	# - its Task Split row on the Story, if this Task came from the split
	#   table - the row's generated_task would point at a name that no
	#   longer exists.
	frappe.db.delete("Task Depends On", {"task": doc.name})

	split_row = frappe.db.get_value("Task Split", {"generated_task": doc.name}, ["name", "parent"])
	if not split_row:
		return

	row_name, story_name = split_row

	# The row goes with it. Leaving the row behind (reset to "not generated")
	# only meant the next Story save recreated the Task, so a deletion from
	# the list view silently undid itself. Deleting from either side now
	# means the same thing - see delete_tasks_for_removed_split_rows for the
	# other direction.
	frappe.db.delete("Task Split", {"name": row_name})

	sync_story_total_from_split(story_name)


def cascade_completion_to_parent(doc, method):
	# Sub-task -> Task, Task -> Story, Story -> Epic all use the same
	# parent_task link, so one generic "recompute from direct children"
	# recursion covers every level instead of writing it three times.
	#
	# The self-recompute first: a status on anything that HAS children is
	# derived, never hand-set. Someone flipping a Story from Working back to
	# Open (or straight to Completed) while its Tasks say otherwise gets
	# overruled here, on their own save, instead of the wrong value sitting
	# there until some child happens to be saved again. Leaf items have no
	# children, so their status stays entirely manual.
	corrected = _sync_status_from_children(doc.name)
	if corrected:
		# Keep the doc the client gets back in step with what we just wrote,
		# and let the later on_update hooks see the real status.
		doc.status = corrected

	if doc.parent_task:
		_sync_status_from_children(doc.parent_task)


def _sync_status_from_children(task_name):
	children = frappe.get_all("Task", filters={"parent_task": task_name}, fields=["status"])
	if not children:
		return

	current_status = frappe.db.get_value("Task", task_name, "status")
	if current_status in ("Cancelled", "Template"):
		return

	# A Task Split row with no expected_hours yet has no generated Task, so it
	# isn't in `children` at all - the Story is still missing planned work and
	# must not be allowed to look Completed.
	split_pending = frappe.db.exists(
		"Task Split", {"parent": task_name, "generated_task": ["in", ("", None)]}
	)

	if not split_pending and all(c.status == "Completed" for c in children):
		new_status = "Completed"
	elif any(c.status != "Open" for c in children):
		# Work has started somewhere below (or finished, with more still to
		# come) - anything short of fully done reads as Working.
		new_status = "Working"
	else:
		new_status = "Open"

	if new_status == current_status:
		return

	frappe.db.set_value("Task", task_name, "status", new_status, update_modified=False)

	parent = frappe.db.get_value("Task", task_name, "parent_task")
	if parent:
		_sync_status_from_children(parent)

	return new_status
