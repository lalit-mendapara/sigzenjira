import json

import frappe
from frappe import _
from frappe.model.utils.user_settings import sync_user_settings, update_user_settings
from frappe.utils import getdate

# Org-wide oversight: every project's board, plus the Department view. Director
# sits here rather than in BOARD_ROLES-only because its remit is the whole org,
# not a project it happens to be a member of.
MANAGER_ROLES = {"Director", "Product Owner", "Projects Manager", "System Manager"}
# Who can open the board at all. Deliberately broad - it is not the gate that
# decides what anyone SEES: _allowed_projects() scopes non-managers to the
# Projects they are a Project User on, and a user on none gets an empty picker.
# Must stay in sync with the `roles` list in page/work_board/work_board.json,
# which is a separate gate on the page itself (frappe's Page.is_permitted is a
# plain role intersection with no System Manager bypass).
BOARD_ROLES = {
	"Employee",
	"Director",
	"Product Owner",
	"Projects User",
	"Projects Manager",
	"System Manager",
}

# Every board shows open work only - Completed/Cancelled are noise when the
# question is "what is still on the line". Applies to the Epic and Story rows
# too, not just the cards.
OPEN_STATUSES = ("Open", "Working", "Pending Review", "Overdue", "Blocked")

# Where a card lands when it is dropped on a column. Several statuses fold into
# one column (STATUS_COLUMN in work_board.js), so a drop has to choose one, and
# it picks the neutral member: Overdue is stamped on by ERPNext's nightly job
# and Blocked is a claim about the work, neither of which a drag should assert.
# Dropping a Blocked card on In Progress therefore leaves it Blocked, because
# that is a move within the same column and never reaches the server.
COLUMN_STATUS = {"To Do": "Open", "In Progress": "Working", "In Review": "Pending Review"}

TASK_FIELDS = ["name", "subject", "status", "exp_end_date", "project", "parent_task", "_assign"]

# Always on the card, so they are never offered as a customisable extra.
BASE_CARD_FIELDS = {"name", "subject", "status", "exp_end_date", "project"}


def _guard_board_access():
	if not BOARD_ROLES & set(frappe.get_roles(frappe.session.user)):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _is_manager():
	return bool(MANAGER_ROLES & set(frappe.get_roles(frappe.session.user)))


def _guard_department_access():
	# The Department board lays out every employee in a department across
	# projects - a project-scoped member has no business seeing it. UI hiding
	# alone is not enough: get_department_board is whitelisted, so it stays
	# callable from the console without this.
	if not _is_manager():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _allowed_projects():
	# None means unrestricted (manager/System Manager). Otherwise: the Projects
	# the session user is a Project User on. Deliberately project-scoped, not
	# own-tasks-only - a member needs to see the whole board of a project they
	# work on, including their teammates' columns.
	if _is_manager():
		return None
	return list(
		set(
			frappe.get_all(
				"Project User",
				filters={"parenttype": "Project", "parentfield": "users", "user": frappe.session.user},
				pluck="parent",
			)
		)
	)


def _check_project(project):
	if not project:
		frappe.throw(_("Project is required"))
	allowed = _allowed_projects()
	if allowed is not None and project not in allowed:
		frappe.throw(_("You are not a member of Project {0}").format(project), frappe.PermissionError)


def _user_info(users):
	if not users:
		return {}
	rows = frappe.get_all(
		"User", filters={"name": ["in", list(users)]}, fields=["name", "full_name", "user_image"]
	)
	return {
		row["name"]: {
			"user": row["name"],
			"full_name": row["full_name"] or row["name"],
			"user_image": row["user_image"],
		}
		for row in rows
	}


def _assignees(row):
	return json.loads(row.get("_assign") or "[]")


def card_field_options():
	"""Task fields a user is allowed to put on a board card.

	permlevel > 0 fields are excluded outright: the board bypasses the form's
	permlevel handling, so anything above level 0 must never leave the server
	through this endpoint.
	"""
	meta = frappe.get_meta("Task")
	return [
		{"fieldname": df.fieldname, "label": _(df.label or df.fieldname), "fieldtype": df.fieldtype}
		for df in meta.fields
		if df.fieldtype not in frappe.model.no_value_fields
		and df.fieldtype != "Password"
		and not df.permlevel
		and df.fieldname not in BASE_CARD_FIELDS
	]


@frappe.whitelist()
def get_card_field_options():
	# Fetched when the Card Fields dialog opens, not folded into get_bootstrap:
	# the dialog must never depend on an earlier call having landed, or it
	# renders an empty checkbox list with no error.
	_guard_board_access()
	return card_field_options()


def _extra_fields(raw):
	# Client-supplied, so it is intersected with card_field_options() rather than
	# trusted - an arbitrary fieldname here would otherwise become a raw column
	# in the SELECT.
	if not raw:
		return []
	selected = json.loads(raw) if isinstance(raw, str) else raw
	allowed = {opt["fieldname"] for opt in card_field_options()}
	return [f for f in selected if f in allowed]


@frappe.whitelist()
def save_card_fields(fields):
	"""Persist the user's card-field picks.

	Not frappe.model.user_settings.save() from the client, for two reasons:
	that path writes to redis only (the __UserSettings flush is the hourly
	sync_user_settings job), so a bench restart before the next flush silently
	loses the pick; and its client-side merge reads frappe.model.user_settings
	[doctype], which only the Task list view populates - saving from the board
	would wipe the list view's filters and vice versa.
	"""
	_guard_board_access()
	fields = _extra_fields(fields)
	update_user_settings("Task", {"work_board_card_fields": fields})
	# ponytail: flushes every cached user setting, not just this row - same work
	# the hourly job already does, now on a click. Narrow it only if the hash
	# grows big enough for that to matter.
	sync_user_settings()
	return fields


@frappe.whitelist()
def set_task_status(task, column):
	"""Move a card between the Task kanban's columns.

	The only write the board makes to a Task. Reading the board is scoped to
	Projects you are a member of, but moving a card is a write, so the gate is
	doc.check_permission("write") rather than the board's own _check_project -
	that runs the role permissions AND custom.permissions.task_has_permission,
	so a member with read-only Task rights gets a board they can look at and
	not drag.
	"""
	_guard_board_access()
	status = COLUMN_STATUS.get(column)
	if not status:
		frappe.throw(_("Unknown board column {0}").format(column))
	doc = frappe.get_doc("Task", task)
	doc.check_permission("write")
	doc.status = status
	# save(), never db_set: a status change has to run the whole Task chain -
	# hour-budget validation, Story/Epic rollup, cascade completion - all of
	# which hangs off validate/on_update in hooks.py.
	doc.save()
	return doc.status


def _task_summary(row, info, project_names=None, extra_fields=None):
	summary = {
		"name": row["name"],
		"subject": row["subject"],
		"status": row["status"],
		"exp_end_date": row.get("exp_end_date"),
		# The Story a Task hangs off - what the Epic board groups its lanes by.
		"parent_task": row.get("parent_task"),
		"assignees": [
			info.get(user) or {"user": user, "full_name": user, "user_image": None}
			for user in _assignees(row)
		],
	}
	if project_names is not None:
		summary["project"] = row.get("project")
		summary["project_name"] = project_names.get(row.get("project"), row.get("project"))
	if extra_fields:
		summary["extra"] = {field: row.get(field) for field in extra_fields}
	return summary


def _sort_tasks(tasks):
	# Soonest due first; undated rows last, then alphabetical - stable, readable
	# column order without a per-card sort control.
	return sorted(tasks, key=lambda t: (t["exp_end_date"] is None, t["exp_end_date"] or "", t["subject"]))


@frappe.whitelist()
def get_bootstrap():
	_guard_board_access()

	allowed = _allowed_projects()
	filters = {"status": ["!=", "Cancelled"]}
	if allowed is not None:
		if not allowed:
			return {"projects": [], "departments": [], "is_manager": False}
		filters["name"] = ["in", allowed]

	projects = frappe.get_all(
		"Project", filters=filters, fields=["name", "project_name"], order_by="project_name asc"
	)
	# Only managers get the Department view, so only they get its dropdown data.
	# Group nodes are folders in the Department tree, never assignable to an
	# Employee - listing them would only ever yield an empty board.
	is_manager = _is_manager()
	departments = (
		frappe.get_all("Department", filters={"is_group": 0}, pluck="name", order_by="name asc")
		if is_manager
		else []
	)
	return {"projects": projects, "departments": departments, "is_manager": is_manager}


def _open_work_items(project, work_item_type, fields):
	"""One row of the board: every open Epic (or Story) in the project.

	Flat, not a descent: the Epic and Story rows always list the whole project and
	the selection that narrows them is applied on the client, so picking a chip
	never costs a query for the rows themselves.
	"""
	return frappe.get_all(
		"Task",
		filters={
			"project": project,
			"custom_task_work_item_type": work_item_type,
			"status": ["in", OPEN_STATUSES],
		},
		fields=fields,
		order_by="creation asc",
	)


def _current_steps(story_names):
	"""Lowest-idx generated, still-open Task Split row per Story.

	The sequence a user recognises is the split row's grid position, NOT the
	generated Task's own name counter: a row only becomes a Task when someone
	fires its Create action, so creating row 2 first makes it T-001 and row 1
	becomes T-002 later. idx is the sequence; the Task contributes only status
	and ID.
	"""
	if not story_names:
		return {}

	rows = frappe.get_all(
		"Task Split",
		filters={"parent": ["in", story_names], "generated_task": ["is", "set"]},
		fields=["parent", "idx", "task_item", "generated_task"],
		order_by="parent asc, idx asc",
	)
	if not rows:
		return {}

	open_tasks = {
		task["name"]: task
		for task in frappe.get_all(
			"Task",
			filters={
				"name": ["in", [r.generated_task for r in rows]],
				"status": ["in", OPEN_STATUSES],
			},
			fields=["name", "status", "_assign"],
		)
	}
	# Resolved here rather than off get_project_board's `info`: the step's Task is
	# not always a card (the ECD range and the Story selection both bound the
	# kanban but not this), so its assignee can be absent from that map.
	names = _user_info({user for task in open_tasks.values() for user in _assignees(task)})

	steps = {}
	for row in rows:
		# OPEN_STATUSES already excludes Completed/Cancelled, so a Task missing
		# from open_tasks IS the skip - the same rule the rest of the board runs
		# on, and it covers a deleted generated_task for free.
		task = open_tasks.get(row.generated_task)
		if row.parent in steps or not task:
			continue
		steps[row.parent] = {
			"idx": row.idx,
			"task_item": row.task_item,
			"task": row.generated_task,
			"status": task["status"],
			"assignees": [(names.get(user) or {}).get("full_name", user) for user in _assignees(task)],
		}
	return steps


def _ecd_range_conditions(from_date, to_date):
	"""ECD range as (filters, or_filters) for get_all - both empty with no bounds.

	A Task with no ECD is never excluded by the range: undated work is still work,
	and the range is there to bound the fetch, not to hide it.

	Two things this has to get right:
	- exp_end_date is a Datetime, so each bound is widened to cover the whole of its
	  day; a plain date comparison would drop anything not sitting at midnight.
	- frappe wraps `<=` in ifnull() (a NULL ECD passes) but not `>=` (a NULL ECD
	  fails). So the lower bound goes through or_filters with an explicit is-not-set
	  beside it, which is what keeps undated Tasks on the board. get_all ANDs the two
	  groups: `base AND ecd <= to AND (ecd is null OR ecd >= from)`.
	"""
	conditions, or_conditions = [], []
	if from_date:
		or_conditions = [
			["exp_end_date", "is", "not set"],
			["exp_end_date", ">=", f"{getdate(from_date)} 00:00:00"],
		]
	if to_date:
		conditions.append(["exp_end_date", "<=", f"{getdate(to_date)} 23:59:59"])
	return conditions, or_conditions


@frappe.whitelist()
def get_project_board(project, stories=None, from_date=None, to_date=None, extra_fields=None):
	"""Three rows of one project: its open Epics, its open Stories, and the kanban.

	`stories` is the client's Epic/Story selection already resolved to Story names -
	an empty list means "the selection matched no Story at all" and empties the
	kanban, while None means nothing is selected and the whole project shows.

	The ECD range bounds only the unselected board, the same way the old picked-item
	board ignored it: once a Story is named, its full set of open Tasks is the answer.
	"""
	_guard_board_access()
	_check_project(project)

	extra = _extra_fields(extra_fields)
	# "" is how the client says "nothing picked" - it must land on None, not on the
	# empty list, which means the opposite.
	if isinstance(stories, str):
		stories = json.loads(stories) if stories else None
	selected = stories

	if selected is None:
		range_filters, range_or_filters = _ecd_range_conditions(from_date, to_date)
		story_filters = []
	else:
		# `["in", []]` is not a query worth sending - the empty selection is answered
		# below without touching the database.
		range_filters, range_or_filters = [], []
		story_filters = [["parent_task", "in", selected]]

	rows = (
		[]
		if selected is not None and not selected
		else frappe.get_all(
			"Task",
			filters=[
				["project", "=", project],
				["custom_task_work_item_type", "=", "Task"],
				["status", "in", OPEN_STATUSES],
				*story_filters,
				*range_filters,
			],
			or_filters=range_or_filters,
			fields=TASK_FIELDS + extra,
		)
	)

	member_users = frappe.get_all(
		"Project User",
		filters={"parenttype": "Project", "parentfield": "users", "parent": project},
		pluck="user",
	)
	# Someone can hold an assignment without being on the Project User table -
	# they still need a column, otherwise their cards would vanish from the
	# employee board entirely.
	assigned_users = {user for row in rows for user in _assignees(row)}
	all_users = list(dict.fromkeys(list(member_users) + sorted(assigned_users)))

	info = _user_info(all_users)
	members = sorted(
		(info.get(user) or {"user": user, "full_name": user, "user_image": None} for user in all_users),
		key=lambda m: m["full_name"],
	)

	# `epic` is the Story's parent - the client groups the Story row by it.
	# `issue` is set for Stories raised through the Issue-to-Story cycle
	# (events/issue.py); the chip links straight back to it.
	story_rows = _open_work_items(
		project, "Story", ["name", "subject", "status", "parent_task as epic", "issue"]
	)
	# Two queries for the whole row rather than one per chip - every Story chip
	# renders its step, so it all ships with the board in one round trip.
	steps = _current_steps([story.name for story in story_rows])
	for story in story_rows:
		story["current_step"] = steps.get(story.name)

	return {
		"tasks": _sort_tasks([_task_summary(row, info, extra_fields=extra) for row in rows]),
		"members": members,
		"epics": _open_work_items(project, "Epic", ["name", "subject", "status"]),
		"stories": story_rows,
		"extra_fields": extra,
	}


@frappe.whitelist()
def get_department_board(department, extra_fields=None):
	_guard_board_access()
	_guard_department_access()
	if not department:
		frappe.throw(_("Department is required"))

	employees = frappe.get_all(
		"Employee",
		filters={"department": department, "status": "Active", "user_id": ["is", "set"]},
		fields=["employee_name", "user_id"],
		order_by="employee_name asc",
	)
	# Employees without a user_id are skipped - nothing can ever be assigned to
	# them, so their column could only ever be empty.
	member_users = list(dict.fromkeys(e["user_id"] for e in employees))
	extra = _extra_fields(extra_fields)
	if not member_users:
		return {"members": [], "tasks": [], "extra_fields": extra}

	info = _user_info(member_users)
	members = [
		{
			"user": e["user_id"],
			"full_name": e["employee_name"],
			"user_image": (info.get(e["user_id"]) or {}).get("user_image"),
		}
		for e in employees
	]

	filters = {"custom_task_work_item_type": "Task", "status": ["in", OPEN_STATUSES]}
	allowed = _allowed_projects()
	if allowed is not None:
		if not allowed:
			return {"members": members, "tasks": [], "extra_fields": extra}
		filters["project"] = ["in", allowed]

	# `like` on the _assign JSON list is only a prefilter to keep the fetch small;
	# it can false-positive on substring emails ("a@x.com" inside "da@x.com"), so
	# the authoritative check is the exact membership test below.
	rows = frappe.get_all(
		"Task",
		filters=filters,
		or_filters=[["_assign", "like", f"%{user}%"] for user in member_users],
		fields=TASK_FIELDS + extra,
	)

	project_names = {
		p["name"]: p["project_name"]
		for p in frappe.get_all(
			"Project",
			filters={"name": ["in", list({row["project"] for row in rows if row["project"]})]},
			fields=["name", "project_name"],
		)
	}
	member_set = set(member_users)
	# _user_info covers the member users; assignees outside the department are
	# kept on the card (the avatar row is the full assignee list) but never get a
	# column of their own.
	assignee_info = _user_info({user for row in rows for user in _assignees(row)})

	tasks = [
		summary
		for summary in (_task_summary(row, assignee_info, project_names, extra_fields=extra) for row in rows)
		if any(a["user"] in member_set for a in summary["assignees"])
	]

	return {"members": members, "tasks": _sort_tasks(tasks), "extra_fields": extra}
