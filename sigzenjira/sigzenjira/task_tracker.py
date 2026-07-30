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
	scoped = []
	for row in rows:
		if row["custom_work_item_type"] != "Task":
			# Epic/Story headers are structural context, not personal work items -
			# a Task assigned to this employee still needs its real parent's
			# subject/status, even when the Epic/Story itself isn't assigned to them.
			scoped.append(row)
			continue
		if employee in _assignees(row):
			scoped.append(row)
	return scoped


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

	stories_by_epic = {}
	for story in stories:
		stories_by_epic.setdefault(story["parent_task"], []).append(story)

	tasks_by_story = {}
	for task in leaf_tasks:
		tasks_by_story.setdefault(task["parent_task"], []).append(task)

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
			# Story-less Tasks can never be Epic-linked directly (validate_hierarchy
			# requires a Task's parent to be a Story or nothing) - they only ever
			# land in the synthetic "No Epic" bucket's own "No Story" row.
			story_list.append(story_dict(None, None))
		return {
			"name": epic_key,
			"subject": epic_row["subject"] if epic_row else "No Epic",
			"status": epic_row["status"] if epic_row else None,
			"story_total": len(story_list),
			"stories": story_list,
		}

	result = [epic_dict(e, e["name"]) for e in sorted(epics, key=lambda e: e["subject"])]
	if stories_by_epic.get(None) or tasks_by_story.get(None):
		result.append(epic_dict(None, None))
	return result


@frappe.whitelist()
def get_tracker_data(project: str | None = None):
	if not set(frappe.get_roles(frappe.session.user)) & {"Projects User", MANAGER_ROLE}:
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	is_manager = _is_manager()

	# Deliberately unscoped: this page's whole point is that Projects Manager sees
	# every task site-wide, regardless of any Project/Company User Permission that
	# would otherwise scope Task for them. See test_manager_sees_every_employees_tasks_in_tree.
	all_rows = frappe.get_all(
		"Task", filters={"custom_work_item_type": ["in", LEAF_WORK_ITEM_TYPES]}, fields=TASK_FIELDS
	)
	all_rows = _scope_to_employee(all_rows, is_manager)

	project_counts = {}
	for row in all_rows:
		if row["project"] and row["custom_work_item_type"] == "Task":
			project_counts[row["project"]] = project_counts.get(row["project"], 0) + 1

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

	# Scoped to the selected project only, same convention as project_counts being
	# scoped to the permission-visible set above - the Employee dropdown lists that
	# project's Task assignees, not every assignee the user can see. Empty when no
	# project is chosen (nothing to scope the list to).
	employee_counts = {}
	if project:
		for row in all_rows:
			if row["project"] == project and row["custom_work_item_type"] == "Task":
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

	epics = _build_epics([r for r in all_rows if r["project"] == project]) if project else []

	return {"projects": projects, "employees": employees, "epics": epics}
