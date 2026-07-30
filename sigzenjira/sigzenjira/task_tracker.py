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
def get_tracker_data(project: str | None = None, employee: str | None = None):
	if not set(frappe.get_roles(frappe.session.user)) & {"Projects User", MANAGER_ROLE}:
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	is_manager = _is_manager()
	if not is_manager:
		employee = frappe.session.user

	# Deliberately unscoped: this page's whole point is that Projects Manager sees
	# every task site-wide, regardless of any Project/Company User Permission that
	# would otherwise scope Task for them. See test_manager_sees_all_employees_tasks.
	all_rows = _expand_assignments(frappe.get_all("Task", fields=TASK_FIELDS))
	if not is_manager:
		all_rows = [r for r in all_rows if r["assigned_to"] == employee]

	project_counts = {}
	employee_counts = {}
	seen_project_tasks = set()
	for row in all_rows:
		if row["project"]:
			task_project_key = (row["project"], row["name"])
			if task_project_key not in seen_project_tasks:
				seen_project_tasks.add(task_project_key)
				project_counts[row["project"]] = project_counts.get(row["project"], 0) + 1
		if row["assigned_to"]:
			employee_counts[row["assigned_to"]] = employee_counts.get(row["assigned_to"], 0) + 1

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

	filtered_rows = all_rows
	if project:
		filtered_rows = [r for r in filtered_rows if r["project"] == project]
	if employee:
		filtered_rows = [r for r in filtered_rows if r["assigned_to"] == employee]

	return {"projects": projects, "employees": employees, "tasks": filtered_rows}
