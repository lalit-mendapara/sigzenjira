import json

import frappe

MANAGER_ROLE = "Projects Manager"

TASK_FIELDS = [
	"name",
	"subject",
	"custom_work_item_type",
	"status",
	"project",
	"parent_task",
	"_assign",
	"exp_end_date",
]

# Sub-task is deliberately excluded: cascade_completion_to_parent (custom/task.py)
# already rolls a Sub-task's completion up into its parent Task's status, so the
# Task card already reflects it - no separate Sub-task row is needed here.
LEAF_WORK_ITEM_TYPES = ("Epic", "Story", "Task")


def _is_manager():
	return MANAGER_ROLE in frappe.get_roles(frappe.session.user)


def _assignees(row):
	return json.loads(row.get("_assign") or "[]")


def _scope_to_employee(rows, is_manager):
	if is_manager:
		return rows
	employee = frappe.session.user

	own_tasks = [r for r in rows if r["custom_work_item_type"] == "Task" and employee in _assignees(r)]
	# Epic/Story headers are structural context, not personal work items - a Task
	# assigned to this employee still needs its real parent's subject/status. But
	# that's ONLY true for the ancestors of the employee's OWN visible Tasks - keeping
	# every Epic/Story row regardless would leak every work-item subject/status in the
	# project to a caller with no assignment there at all (get_tracker_data's `project`
	# is caller-supplied). So prune to exactly the Story/Epic chain above own_tasks.
	story_names = {t["parent_task"] for t in own_tasks if t["parent_task"]}
	kept_stories = [r for r in rows if r["custom_work_item_type"] == "Story" and r["name"] in story_names]
	epic_names = {s["parent_task"] for s in kept_stories if s["parent_task"]}
	kept_epics = [r for r in rows if r["custom_work_item_type"] == "Epic" and r["name"] in epic_names]
	return own_tasks + kept_stories + kept_epics


def _task_summary(row):
	return {
		"name": row["name"],
		"subject": row["subject"],
		"status": row["status"],
		"exp_end_date": row.get("exp_end_date"),
		"assignees": _assignees(row),
	}


def _build_epics(rows):
	epics = [r for r in rows if r["custom_work_item_type"] == "Epic"]
	stories = [r for r in rows if r["custom_work_item_type"] == "Story"]
	leaf_tasks = [r for r in rows if r["custom_work_item_type"] == "Task"]

	# Keys are coerced to the synthetic None bucket whenever the parent isn't
	# actually present in `rows` - out-of-project/out-of-scope parent, a dangling
	# parent_task, or (legacy data) a Task parented straight at an Epic. Without
	# this, a Story/Task whose parent row didn't survive the caller's project
	# filter is unreachable: it sits in stories_by_epic/tasks_by_story under a key
	# that no epic_dict/story_dict call ever looks up, and silently vanishes.
	epic_keys = {e["name"] for e in epics}
	story_keys = {s["name"] for s in stories}

	stories_by_epic = {}
	for story in stories:
		key = story["parent_task"] if story["parent_task"] in epic_keys else None
		stories_by_epic.setdefault(key, []).append(story)

	tasks_by_story = {}
	for task in leaf_tasks:
		key = task["parent_task"] if task["parent_task"] in story_keys else None
		tasks_by_story.setdefault(key, []).append(task)

	def story_dict(story_row, story_key):
		story_tasks = sorted(tasks_by_story.get(story_key, []), key=lambda t: t["subject"])
		return {
			"name": story_key,
			"subject": story_row["subject"] if story_row else "No Story",
			"status": story_row["status"] if story_row else None,
			"task_total": len(story_tasks),
			"tasks": [_task_summary(t) for t in story_tasks],
		}

	def epic_dict(epic_row, epic_key):
		child_stories = sorted(stories_by_epic.get(epic_key, []), key=lambda s: s["subject"])
		story_list = [story_dict(s, s["name"]) for s in child_stories]
		if epic_key is None and tasks_by_story.get(None):
			# The synthetic "No Epic" bucket's own "No Story" row is the catch-all
			# for: Story-less Tasks (validate_hierarchy forbids a Task parented
			# directly to an Epic), Tasks whose Story parent didn't survive the
			# project/permission scope, and Tasks with a dangling parent_task -
			# not just the never-directly-under-an-Epic case.
			story_list.append(story_dict(None, None))
		return {
			"name": epic_key,
			"subject": epic_row["subject"] if epic_row else "No Epic",
			"status": epic_row["status"] if epic_row else None,
			"stories": story_list,
		}

	result = [epic_dict(e, e["name"]) for e in sorted(epics, key=lambda e: e["subject"])]
	if stories_by_epic.get(None) or tasks_by_story.get(None):
		result.append(epic_dict(None, None))
	return result


def _project_counts(is_manager):
	# Deliberately unscoped by *selected* project - this badge is the Project
	# dropdown's own count, same site-wide-for-managers convention as the rest of
	# this module. See test_sidebar_totals_are_unfiltered_by_current_selection.
	if is_manager:
		counts = frappe.get_all(
			"Task",
			filters={"custom_work_item_type": "Task", "project": ["is", "set"]},
			fields=["project", {"COUNT": "name", "as": "task_count"}],
			group_by="project",
		)
		return {c["project"]: c["task_count"] for c in counts}

	# Non-manager: can't group-count in SQL and stay exact, because "assigned to
	# me" lives in the _assign JSON list, not a column. The `like` filter is only
	# a prefilter to keep the row-set small (avoids a site-wide 8-field fetch) -
	# `like` can false-positive on substring emails (e.g. "a@x.com" inside
	# "da@x.com"), so the authoritative check is still the exact Python
	# membership test below before anything gets counted.
	user = frappe.session.user
	rows = frappe.get_all(
		"Task",
		filters={
			"custom_work_item_type": "Task",
			"project": ["is", "set"],
			"_assign": ["like", f"%{user}%"],
		},
		fields=["project", "_assign"],
	)
	counts = {}
	for row in rows:
		if user in _assignees(row):
			counts[row["project"]] = counts.get(row["project"], 0) + 1
	return counts


@frappe.whitelist()
def get_tracker_data(project: str | None = None):
	if not set(frappe.get_roles(frappe.session.user)) & {"Projects User", MANAGER_ROLE}:
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	is_manager = _is_manager()

	project_counts = _project_counts(is_manager)

	project_names = {}
	if project_counts:
		for proj in frappe.get_all(
			"Project", filters={"name": ["in", list(project_counts.keys())]}, fields=["name", "project_name"]
		):
			project_names[proj["name"]] = proj["project_name"]

	projects = [
		{"name": name, "project_name": project_names.get(name, name), "task_count": count}
		for name, count in project_counts.items()
	]
	projects.sort(key=lambda p: p["project_name"])

	# Tree rows are fetched for the selected project only - the global fetch this
	# replaced pulled every Epic/Story/Task site-wide (8 fields incl. _assign) just
	# to answer the badge counts above, which are now their own query.
	project_rows = []
	if project:
		project_rows = frappe.get_all(
			"Task",
			filters={"custom_work_item_type": ["in", LEAF_WORK_ITEM_TYPES], "project": project},
			fields=TASK_FIELDS,
		)
		project_rows = _scope_to_employee(project_rows, is_manager)

	# Employee dropdown lists this project's Task assignees, not every assignee
	# the user can see - same convention as project_counts above. Empty when no
	# project is chosen (nothing to scope the list to).
	employee_counts = {}
	for row in project_rows:
		if row["custom_work_item_type"] == "Task":
			for user in _assignees(row):
				employee_counts[user] = employee_counts.get(user, 0) + 1

	full_names = {}
	if employee_counts:
		for user in frappe.get_all(
			"User", filters={"name": ["in", list(employee_counts.keys())]}, fields=["name", "full_name"]
		):
			full_names[user["name"]] = user["full_name"]

	employees = [
		{"name": name, "full_name": full_names.get(name, name), "task_count": count}
		for name, count in employee_counts.items()
	]
	employees.sort(key=lambda e: e["full_name"])

	epics = _build_epics(project_rows) if project else []

	return {"projects": projects, "employees": employees, "epics": epics}
