import json

import frappe

MANAGER_ROLE = "Projects Manager"

TASK_FIELDS = ["name", "subject", "custom_work_item_type", "status", "project", "_assign"]


def _is_manager():
	return MANAGER_ROLE in frappe.get_roles(frappe.session.user)


def _expand_assignments(tasks):
	rows = []
	for task in tasks:
		assignees = json.loads(task.get("_assign") or "[]") or [None]
		for user in assignees:
			rows.append(
				{
					"name": task["name"],
					"subject": task["subject"],
					"work_item_type": task["custom_work_item_type"],
					"status": task["status"],
					"project": task["project"],
					"assigned_to": user,
				}
			)
	return rows


@frappe.whitelist()
def get_tracker_data(project=None, employee=None):
	is_manager = _is_manager()
	if not is_manager:
		employee = frappe.session.user

	all_rows = _expand_assignments(frappe.get_all("Task", fields=TASK_FIELDS))
	if not is_manager:
		all_rows = [r for r in all_rows if r["assigned_to"] == employee]

	project_counts = {}
	employee_counts = {}
	for row in all_rows:
		if row["project"]:
			project_counts[row["project"]] = project_counts.get(row["project"], 0) + 1
		if row["assigned_to"]:
			employee_counts[row["assigned_to"]] = employee_counts.get(row["assigned_to"], 0) + 1

	projects = []
	for name, count in project_counts.items():
		project_name = frappe.db.get_value("Project", name, "project_name") or name
		projects.append({"name": name, "project_name": project_name, "task_count": count})
	projects.sort(key=lambda p: p["project_name"])

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

	task_filters = {}
	if project:
		task_filters["project"] = project
	filtered_rows = _expand_assignments(frappe.get_all("Task", filters=task_filters, fields=TASK_FIELDS))
	if employee:
		filtered_rows = [r for r in filtered_rows if r["assigned_to"] == employee]

	return {"projects": projects, "employees": employees, "tasks": filtered_rows}
