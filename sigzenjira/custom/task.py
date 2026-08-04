import json

import frappe
from frappe import _
from frappe.desk.form import assign_to
from frappe.model.naming import make_autoname
from frappe.utils import cint, flt, get_link_to_form, getdate

from sigzenjira.custom.project_user import user_has_project_flag

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
	prefix = WORK_ITEM_TYPE_NAME_PREFIX.get(doc.custom_work_item_type, "T")
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
	# Only these roles may classify a Task as Epic/Story/Task - everyone
	# else (Employee) is restricted to Sub-task, per the org's approval
	# hierarchy. Checked against the previous saved value (like
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

	previous_value = None if doc.is_new() else (doc.get_doc_before_save() or {}).get("custom_work_item_type")
	if doc.custom_work_item_type == previous_value:
		return

	if doc.custom_work_item_type != "Sub-task":
		frappe.throw(
			_(
				"Only a Director, Product Owner, or Projects Manager can set Work Item Type to {0}. You can only create a Sub-task."
			).format(doc.custom_work_item_type)
		)


def validate_hierarchy(doc, method):
	expected_parent_type = EXPECTED_PARENT_TYPE.get(doc.custom_work_item_type)

	if expected_parent_type is None:
		if doc.parent_task:
			frappe.throw(_("An Epic cannot have a parent task."))
		return

	if not doc.parent_task:
		if doc.custom_work_item_type in OPTIONAL_PARENT_TYPES:
			return
		frappe.throw(
			_("A {0} must have a parent task of type {1}.").format(
				doc.custom_work_item_type, expected_parent_type
			)
		)

	parent_work_item_type = frappe.db.get_value("Task", doc.parent_task, "custom_work_item_type")
	if parent_work_item_type != expected_parent_type:
		frappe.throw(
			_("A {0}'s parent task {1} must be of type {2}, not {3}.").format(
				doc.custom_work_item_type,
				get_link_to_form("Task", doc.parent_task),
				expected_parent_type,
				parent_work_item_type or _("unset"),
			)
		)


def block_manual_task_under_story(doc, method):
	# A Story's Tasks come only from its Task Split grid
	# (generate_tasks_from_split). task.js hides the "Create Task" button on a
	# Story, but the list view, the API and the Work Board can all still land a
	# Task here - and one with no split row is invisible to
	# rollup_story_expected_time (which derives the Story's total from the rows
	# alone) while still counting against it in validate_hour_budget. Enforce
	# the same rule server-side, where every write path goes through.
	if doc.custom_work_item_type != "Task" or not doc.parent_task:
		return

	if frappe.db.get_value("Task", doc.parent_task, "custom_work_item_type") != "Story":
		return

	if frappe.db.exists("Task Split", {"parent": doc.parent_task, "generated_task": doc.name}):
		return

	# The legitimate split path inserts the Task BEFORE writing generated_task
	# back onto the row, so during that window the only proof the Task belongs
	# to a row is the is_generating claim generate_tasks_from_split sets first.
	if doc.is_new() and frappe.db.exists("Task Split", {"parent": doc.parent_task, "is_generating": 1}):
		return

	frappe.throw(
		_("Add Tasks to {0} through its Task Split table, not directly.").format(
			get_link_to_form("Task", doc.parent_task)
		)
	)


EXPECTED_TIME_RESTRICTED_TYPES = {"Epic"}
EXPECTED_TIME_PRIVILEGED_ROLES = {"Projects Manager", "System Manager"}


def validate_expected_time_edit_permission(doc, method):
	# Epic's budget is a planning decision, not something a developer
	# estimating their own Tasks should be able to move. Story is excluded
	# here on purpose: rollup_story_expected_time below now derives it from
	# custom_task_split, so whoever fills that table (per spec, not
	# necessarily a Projects Manager) drives the number - see
	# validate_hour_budget for why Task/Sub-task's expected_time stays open.
	if doc.custom_work_item_type not in EXPECTED_TIME_RESTRICTED_TYPES:
		return

	if EXPECTED_TIME_PRIVILEGED_ROLES & set(frappe.get_roles(frappe.session.user)):
		return

	previous_expected_time = (
		0 if doc.is_new() else flt((doc.get_doc_before_save() or {}).get("expected_time"))
	)
	if flt(doc.expected_time) != previous_expected_time:
		frappe.throw(_("Only a Projects Manager can set or change Expected Time on an Epic."))


def sync_actual_extra_hours(doc, method):
	# recompute_actual_time (custom/timesheet.py) covers the Timesheet-driven
	# path via a raw db.set_value that bypasses validate(); this covers a plain
	# doc.save() that only changes expected_time. Positive = over budget,
	# negative = under - no floor at zero.
	doc.custom_actual_extra_hours = flt(doc.actual_time) - flt(doc.expected_time)


def validate_task_split_expected_hours_permission(doc, method):
	# Expected Hours is the budget commitment on a split row - only a Project
	# User flagged custom_allocate_hours (or Administrator/System Manager,
	# via user_has_project_flag) for this Task's project may set or change it.
	# Re-checked here since the Desk grid (task.js) only makes the column
	# read-only client-side, not real enforcement against direct API calls.
	if doc.custom_work_item_type != "Story":
		return

	if user_has_project_flag(doc.project, "custom_allocate_hours"):
		return

	before = doc.get_doc_before_save()
	before_rows = {row.name: flt(row.expected_hours) for row in (before.custom_task_split if before else [])}

	for row in doc.get("custom_task_split") or []:
		previous_hours = before_rows.get(row.name, 0)
		if flt(row.expected_hours) != previous_hours:
			frappe.throw(
				_(
					"Only a user with Allocate Hours access on this Project can set Expected Hours on the Task Split table."
				)
			)


def validate_task_split_assign_permission(doc, method):
	# Assign is the other budget-adjacent commitment on a split row - only a
	# Project User flagged custom_assign_users (or Administrator/System
	# Manager, via user_has_project_flag) for this Task's project may stage
	# assignees on a not-yet-generated row. Re-checked here since the Desk
	# grid's Assign dialog (task.js) only hides/disables client-side, not
	# real enforcement against direct API calls. The generated_task case is
	# gated separately in set_split_row_assignees below.
	if doc.custom_work_item_type != "Story":
		return

	if user_has_project_flag(doc.project, "custom_assign_users"):
		return

	before = doc.get_doc_before_save()
	before_rows = {row.name: row.pending_assign_users for row in (before.custom_task_split if before else [])}

	for row in doc.get("custom_task_split") or []:
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
	if doc.custom_work_item_type != "Story" or not doc.issue:
		return

	existing = frappe.db.exists(
		"Task",
		{
			"issue": doc.issue,
			"custom_work_item_type": "Story",
			"name": ["!=", doc.name or ""],
			"docstatus": ["!=", 2],
		},
	)
	if existing:
		frappe.throw(
			_("Issue {0} already has a Story: {1}.").format(doc.issue, get_link_to_form("Task", existing))
		)


def sync_issue_status_on_story_completion(doc, method):
	# Direct-save path only (user marks the Story itself Completed) - cascade
	# auto-completion from children deliberately does NOT close the Issue.
	if doc.custom_work_item_type != "Story" or not doc.issue or doc.status != "Completed":
		return

	if frappe.db.get_value("Issue", doc.issue, "status") != "Resolved":
		frappe.db.set_value("Issue", doc.issue, "status", "Resolved")


EMPLOYEE_STORY_LOCKED_EXCEPTIONS = {"custom_task_template", "expected_time"}
# expected_time is excepted because rollup_story_expected_time recomputes it
# automatically from custom_task_split whenever rows change - it's a derived
# side effect of picking a template, not something the Employee sets directly.


def validate_employee_story_field_restriction(doc, method):
	# A Story always already exists by the time an Employee can reach it
	# (validate_work_item_type_permission keeps them from creating one from
	# scratch) - the one thing they're allowed to do on it is pick a Task
	# Template. Everything else - subject, priority, dates, status, the
	# split table's row content - stays whoever created/owns the Story's call.
	if doc.is_new() or doc.custom_work_item_type != "Story":
		return

	if WORK_ITEM_TYPE_PRIVILEGED_ROLES & set(frappe.get_roles(frappe.session.user)):
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
	# The split table is what a Story's hours actually come from - the PM
	# shouldn't pre-declare a total before splitting, then hope it matches.
	# Only overrides when split rows exist; a Story with none yet (or ones
	# created without ever using the split table) keeps whatever expected_time
	# it already has, so validate_hour_budget below still has a number to
	# check standalone/legacy Stories against.
	if doc.custom_work_item_type != "Story":
		return

	split_rows = doc.get("custom_task_split") or []
	if not split_rows:
		return

	doc.expected_time = sum(flt(row.expected_hours) for row in split_rows)


def delete_tasks_for_removed_split_rows(doc, method):
	# A split row and its generated Task are the same work item seen from two
	# places - dropping the row from the grid has to take the Task with it,
	# otherwise the Story keeps a child that traces back to no plan line.
	# Frappe has already deleted the removed rows from the DB by now, so the
	# pre-save snapshot is the only place their generated_task still exists.
	if doc.custom_work_item_type != "Story":
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	kept = {row.name for row in doc.get("custom_task_split") or []}
	for old_row in before.get("custom_task_split") or []:
		if old_row.name in kept or not old_row.generated_task:
			continue
		if not frappe.db.exists("Task", old_row.generated_task):
			continue
		# Deliberately not forced: core blocks deleting a Task that has
		# sub-tasks or linked Timesheets, and dropping a plan line that
		# already has real work under it should fail loudly, not silently
		# take the work with it.
		frappe.delete_doc("Task", old_row.generated_task)


# INVARIANT: a raw frappe.db.set_value to a billable flag skips validate(), so
# it bypasses the billable clamp entirely (custom/billable.py). The only two
# sanctioned exceptions are the Task Split <-> generated Task mirror: this
# function (row -> Task.custom_is_billable) and sync_expected_hours_to_split_row
# below (Task -> row.is_billable). Both are safe only because the doc being
# mirrored FROM was itself clamped on the save that triggered them - and the
# row -> Task direction still needs validate_split_row_unbilling
# (custom/billable.py) to stand in for the validate() it skips, because a row
# going 1 -> 0 can strand billable Sub-tasks under the generated Task. Any new
# raw write to either field must name the guard that covers it, or use save().
def sync_split_row_edits_to_generated_task(doc, method):
	# generate_tasks_from_split deliberately ignores edits to an
	# already-generated row's expected_hours (see its own comment) - that
	# only means "don't regenerate the Task", not "don't push the edit
	# through". Without this, editing an already-split row never reaches the
	# Task it created.
	if doc.custom_work_item_type != "Story":
		return

	for row in doc.get("custom_task_split") or []:
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
			frappe.db.get_value("Task", row.generated_task, "custom_is_billable")
		):
			frappe.db.set_value(
				"Task", row.generated_task, "custom_is_billable", cint(row.is_billable), update_modified=False
			)


def validate_hour_budget(doc, method):
	# A standalone Story/Task (no parent) has no budget to check against.
	if doc.custom_work_item_type not in BUDGET_CHECKED_TYPES or not doc.parent_task:
		return

	parent_budget = flt(frappe.db.get_value("Task", doc.parent_task, "expected_time"))
	if not parent_budget:
		# Epic/Story not every time carry a declared budget - nothing to check against.
		return

	sibling_hours = flt(
		frappe.db.sql(
			"""
			select sum(expected_time) from `tabTask`
			where parent_task = %s and custom_work_item_type = %s and name != %s
			""",
			(doc.parent_task, doc.custom_work_item_type, doc.name or ""),
		)[0][0]
	)

	total_hours = sibling_hours + flt(doc.expected_time)

	if total_hours > parent_budget:
		frappe.throw(
			_("Total {0} hours under parent task {1} would be {2}h, exceeding its budget of {3}h.").format(
				doc.custom_work_item_type,
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
	if doc.custom_work_item_type != "Story":
		return

	for row in doc.get("custom_task_split") or []:
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
				"custom_work_item_type": "Task",
				"expected_time": row.expected_hours,
				"custom_is_billable": row.is_billable,
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
	if doc.custom_work_item_type != "Task" or not doc.parent_task:
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
			"is_billable": cint(doc.custom_is_billable),
		},
	)

	story_total = flt(
		frappe.db.sql("select sum(expected_hours) from `tabTask Split` where parent = %s", story_name)[0][0]
	)
	frappe.db.set_value("Task", story_name, "expected_time", story_total, update_modified=False)


@frappe.whitelist()
def get_task_split_permissions(project=None):
	# Backs the Desk grid's read-only/disabled lock on Task Split's Expected
	# Hours column and Assign action (task.js) - client-side query of the
	# same validate_task_split_expected_hours_permission /
	# validate_task_split_assign_permission gates.
	return {
		"allocate_hours": user_has_project_flag(project, "custom_allocate_hours"),
		"assign_users": user_has_project_flag(project, "custom_assign_users"),
	}


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
	if not user_has_project_flag(project, "custom_assign_users"):
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
	if not user_has_project_flag(story.project, "custom_allocate_hours"):
		frappe.throw(
			_("Only a user with Allocate Hours access on this Project can create a Task from this row.")
		)

	frappe.db.set_value("Task Split", row_name, "is_generating", 1)

	task = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": f"{row.task_item} - {story.subject}",
			"project": story.project,
			"parent_task": story.name,
			"description": row.description,
			"custom_work_item_type": "Task",
			"priority": story.priority,
			"exp_end_date": row.ecd,
			"custom_is_billable": row.is_billable,
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

	story_total = flt(
		frappe.db.sql("select sum(expected_hours) from `tabTask Split` where parent = %s", story_name)[0][0]
	)
	frappe.db.set_value("Task", story_name, "expected_time", story_total, update_modified=False)


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
		# and let the later on_update hooks (issue sync) see the real status.
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
