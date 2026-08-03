import json

import frappe
from frappe import _
from frappe.utils import getdate

# Org-wide oversight: every project's board, plus the Department view. Director
# sits here rather than in BOARD_ROLES-only because its remit is the whole org,
# not a project it happens to be a member of.
MANAGER_ROLES = {"Director", "Projects Manager", "System Manager"}
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

WORK_ITEM_TYPES = ("Epic", "Story", "Task")

# Every board shows open work only - Completed/Cancelled are noise when the
# question is "what is still on the line".
OPEN_STATUSES = ("Open", "Working", "Pending Review", "Overdue", "Blocked")

# The two statuses the stat tiles count and filter by.
STAT_STATUSES = ("Open", "Working")

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


@frappe.whitelist()
def search_work_items(project, txt=None):
	# One picker across all three levels - the work item's own type is what
	# decides how the board is built, so it is never a separate input.
	_guard_board_access()
	_check_project(project)

	or_filters = None
	if txt:
		or_filters = {"name": ["like", f"%{txt}%"], "subject": ["like", f"%{txt}%"]}

	return frappe.get_all(
		"Task",
		filters={"project": project, "custom_work_item_type": ["in", WORK_ITEM_TYPES]},
		or_filters=or_filters,
		fields=["name", "subject", "status", "custom_work_item_type as work_item_type"],
		order_by="custom_work_item_type asc, modified desc",
		limit=20,
	)


def _descendant_tasks(item, work_item_type, fields=None, story_names=None):
	# Fixed 4-level hierarchy (Epic > Story > Task > Sub-task), so descent is two
	# flat queries, no recursion. Sub-tasks are never cards:
	# cascade_completion_to_parent (custom/task.py) already rolls their completion
	# into the parent Task's status.
	fields = fields or TASK_FIELDS
	if work_item_type == "Task":
		return frappe.get_all("Task", filters={"name": item, "status": ["in", OPEN_STATUSES]}, fields=fields)

	story_parents = [item]
	if work_item_type == "Epic":
		# story_names is the stat-tile filter's answer: [] means "the tile matched
		# nothing", which is not the same as "no filter" (None).
		story_parents = (
			story_names
			if story_names is not None
			else frappe.get_all(
				"Task", filters={"parent_task": item, "custom_work_item_type": "Story"}, pluck="name"
			)
		)
		if not story_parents:
			return []

	return frappe.get_all(
		"Task",
		filters={
			"parent_task": ["in", story_parents],
			"custom_work_item_type": "Task",
			"status": ["in", OPEN_STATUSES],
		},
		fields=fields,
	)


def _epic_stories(item):
	"""The Stories directly under an Epic - one board lane each.

	Unlike the cards, Completed/Cancelled Stories are kept: the lanes exist to show
	how far the Epic has got, and dropping the finished ones would read as if that
	work had never been planned.
	"""
	return frappe.get_all(
		"Task",
		filters={"parent_task": item, "custom_work_item_type": "Story"},
		# `issue` is set for Stories raised through the Issue-to-Story cycle
		# (custom/issue.py) - the lane links straight back to it.
		fields=["name", "subject", "status", "issue"],
		order_by="creation asc",
	)


def _project_stats(project):
	"""Open/Working counts of the project's Epics and Stories, for the stat tiles.

	Deliberately project-wide: the tiles read as "this is what the project holds",
	so they are not narrowed by the picked work item, the date range, or the tile
	filter itself (a filtered tile would otherwise change its own count on click).
	"""
	rows = frappe.get_all(
		"Task",
		filters={
			"project": project,
			"custom_work_item_type": ["in", ("Epic", "Story")],
			"status": ["in", STAT_STATUSES],
		},
		fields=["custom_work_item_type", "status", {"COUNT": "name", "as": "count"}],
		group_by="custom_work_item_type, status",
	)
	stats = {work_item: dict.fromkeys(STAT_STATUSES, 0) for work_item in ("Epic", "Story")}
	for row in rows:
		stats[row["custom_work_item_type"]][row["status"]] = row["count"]
	return stats


def _stat_filter_stories(project, stat_type, stat_status, epic=None):
	"""Story names a stat tile allows through, or None when no tile is active.

	Both tile kinds resolve to a set of Stories, because Stories are what the
	board lays out: "Story Working" is the Working Stories, "Epic Open" is every
	Story under an Open Epic.
	"""
	if stat_type not in ("Epic", "Story") or stat_status not in STAT_STATUSES:
		return None

	filters = {"project": project, "custom_work_item_type": "Story"}
	if stat_type == "Story":
		filters["status"] = stat_status
		if epic:
			filters["parent_task"] = epic
	else:
		epics = frappe.get_all(
			"Task",
			filters={"project": project, "custom_work_item_type": "Epic", "status": stat_status},
			pluck="name",
		)
		if not epics or (epic and epic not in epics):
			return []
		filters["parent_task"] = epic if epic else ["in", epics]

	return frappe.get_all("Task", filters=filters, pluck="name")


def _stories_detail(names):
	"""Lane headers for the project-wide board: which Stories these cards sit under.

	The Epic board groups by _epic_stories, but a project-wide board has no picked
	item to group by - a tile click would otherwise say "6 Stories Working" without
	ever saying which six. The Epic each Story hangs off comes along for the same
	reason: on this board nothing else names it.
	"""
	if not names:
		return []
	stories = frappe.get_all(
		"Task",
		filters={"name": ["in", list(names)]},
		fields=["name", "subject", "status", "parent_task", "issue"],
		order_by="creation asc",
	)
	epic_names = {story["parent_task"] for story in stories if story["parent_task"]}
	epics = (
		{
			row["name"]: row["subject"]
			for row in frappe.get_all("Task", filters={"name": ["in", list(epic_names)]}, fields=["name", "subject"])
		}
		if epic_names
		else {}
	)
	for story in stories:
		story["epic"] = story["parent_task"]
		story["epic_subject"] = epics.get(story["parent_task"])
	return stories


def _ecd_range_conditions(from_date, to_date):
	"""ECD range as get_all conditions - empty when neither bound is given.

	Two things this has to get right:
	- exp_end_date is a Datetime, so each bound is widened to cover the whole of its
	  day; a plain date comparison would drop anything not sitting at midnight.
	- frappe wraps comparisons in ifnull(), so a Task with no ECD would otherwise
	  satisfy `<= to_date`. The explicit is-set condition is what keeps undated Tasks
	  off the board while the range is on.
	"""
	if not from_date and not to_date:
		return []
	conditions = [["exp_end_date", "is", "set"]]
	if from_date:
		conditions.append(["exp_end_date", ">=", f"{getdate(from_date)} 00:00:00"])
	if to_date:
		conditions.append(["exp_end_date", "<=", f"{getdate(to_date)} 23:59:59"])
	return conditions


@frappe.whitelist()
def get_project_board(
	project,
	item=None,
	from_date=None,
	to_date=None,
	extra_fields=None,
	stat_type=None,
	stat_status=None,
):
	_guard_board_access()
	_check_project(project)

	extra = _extra_fields(extra_fields)
	work_item_type = None
	stat_stories = None

	if not item:
		# Default board for a freshly picked Project: its Tasks whose ECD falls in
		# the toolbar's date range (the page defaults that to the current month), so
		# the first load is bounded instead of pulling the project's whole history.
		# The range deliberately does not apply once a work item is picked - that
		# board always shows its full tree.
		stat_stories = _stat_filter_stories(project, stat_type, stat_status)
		rows = (
			[]
			if stat_stories == []
			else frappe.get_all(
				"Task",
				filters=[
					["project", "=", project],
					["custom_work_item_type", "=", "Task"],
					["status", "in", OPEN_STATUSES],
					*([["parent_task", "in", stat_stories]] if stat_stories else []),
					*_ecd_range_conditions(from_date, to_date),
				],
				fields=TASK_FIELDS + extra,
			)
		)
	else:
		item_row = frappe.db.get_value("Task", item, ["project", "custom_work_item_type"], as_dict=True)
		if not item_row or item_row.project != project:
			# Also the anti-tampering check: a caller can't pass an item from a
			# project they aren't a member of, because _check_project already vetted
			# `project` and the item must live inside it.
			frappe.throw(_("{0} is not a work item of Project {1}").format(item, project))

		# The item's own type drives how the board is assembled; Sub-tasks are not
		# board roots (they never carry cards of their own).
		work_item_type = item_row.custom_work_item_type
		if work_item_type not in WORK_ITEM_TYPES:
			frappe.throw(_("{0} cannot be shown on the board").format(item))

		# A tile only narrows a board that lays Stories out; a Story or Task board
		# is already one item deep, so the tiles are inert there (the client greys
		# them out to match).
		if work_item_type == "Epic":
			stat_stories = _stat_filter_stories(project, stat_type, stat_status, epic=item)

		rows = _descendant_tasks(item, work_item_type, TASK_FIELDS + extra, story_names=stat_stories)

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

	# Only an Epic has Stories to lay out beside its board, and an active tile
	# drops the lanes it filtered out along with their cards.
	if work_item_type == "Epic":
		stories = _epic_stories(item)
		if stories and stat_stories is not None:
			allowed = set(stat_stories)
			stories = [story for story in stories if story["name"] in allowed]
	elif not item:
		# Every Story the board could group by: the ones a tile matched (kept even
		# with no open Task, that emptiness is the answer to "which Stories are
		# Open") plus the parents of the cards themselves, which is what the
		# client's Overdue filter groups by. The client decides when to use them.
		stories = _stories_detail(
			set(stat_stories or []) | {row["parent_task"] for row in rows if row.get("parent_task")}
		)
	else:
		stories = []

	return {
		"tasks": _sort_tasks([_task_summary(row, info, extra_fields=extra) for row in rows]),
		"members": members,
		"context": _ancestry(item) if item else [],
		"stories": stories,
		"stats": _project_stats(project),
		"extra_fields": extra,
	}


def _ancestry(item):
	# Selected item first, then its parents, so the board can show "this Story is
	# Working, and the Epic above it is Open" without a second round trip. At most
	# 3 hops (Task > Story > Epic), and it stops at whatever the chain ends on.
	chain = []
	name = item
	while name and len(chain) < 3:
		row = frappe.db.get_value(
			"Task", name, ["name", "subject", "status", "custom_work_item_type", "parent_task"], as_dict=True
		)
		if not row:
			break
		chain.append(
			{
				"name": row.name,
				"subject": row.subject,
				"status": row.status,
				"work_item_type": row.custom_work_item_type,
			}
		)
		name = row.parent_task
	# Outermost ancestor first - reads Epic > Story > Task, same order as the
	# hierarchy itself.
	return list(reversed(chain))


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

	filters = {"custom_work_item_type": "Task", "status": ["in", OPEN_STATUSES]}
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
