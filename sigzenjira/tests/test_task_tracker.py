import json

import frappe
from frappe.desk.form import assign_to
from frappe.tests import IntegrationTestCase

from sigzenjira.install import add_task_tracker_workspace_shortcut
from sigzenjira.sigzenjira.task_tracker import get_tracker_data

MANAGER_USER = "test_tracker_manager@example.com"
EMPLOYEE_USER = "test_tracker_employee@example.com"
OTHER_EMPLOYEE_USER = "test_tracker_other_employee@example.com"


def ensure_user(email, first_name, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
	return email


def make_task(subject, project=None, assignee=None, work_item_type="Task"):
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_work_item_type": work_item_type,
			"project": project,
		}
	)
	doc.insert(ignore_permissions=True)
	if assignee:
		assign_to.add({"assign_to": [assignee], "doctype": "Task", "name": doc.name})
	return doc


def ensure_project(project_name):
	existing = frappe.db.get_value("Project", {"project_name": project_name})
	if existing:
		return existing
	return frappe.get_doc({"doctype": "Project", "project_name": project_name}).insert(ignore_permissions=True).name


class TestTaskTracker(IntegrationTestCase):
	def test_manager_sees_all_employees_tasks(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		other = ensure_user(OTHER_EMPLOYEE_USER, "Tracker Other", ["Projects User"])

		make_task("TT Manager Visible 1", assignee=employee)
		make_task("TT Manager Visible 2", assignee=other)

		frappe.set_user(manager)
		try:
			data = get_tracker_data()
		finally:
			frappe.set_user("Administrator")

		assigned_users = {t["assigned_to"] for t in data["tasks"]}
		self.assertIn(employee, assigned_users)
		self.assertIn(other, assigned_users)

	def test_employee_cannot_see_others_tasks_even_when_requested(self):
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		other = ensure_user(OTHER_EMPLOYEE_USER, "Tracker Other", ["Projects User"])

		make_task("TT Own Task", assignee=employee)
		make_task("TT Other Task", assignee=other)

		frappe.set_user(employee)
		try:
			data = get_tracker_data(employee=other)
		finally:
			frappe.set_user("Administrator")

		assigned_users = {t["assigned_to"] for t in data["tasks"]}
		self.assertEqual(assigned_users, {employee})

	def test_project_and_employee_filters_combine(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		project = ensure_project("TT Project A")

		make_task("TT In Project", project=project, assignee=employee)
		make_task("TT Outside Project", assignee=employee)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project, employee=employee)
		finally:
			frappe.set_user("Administrator")

		subjects = {t["subject"] for t in data["tasks"]}
		self.assertEqual(subjects, {"TT In Project"})

	def test_sidebar_totals_are_unfiltered_by_current_selection(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		project_a = ensure_project("TT Project A")
		project_b = ensure_project("TT Project B")

		make_task("TT Sidebar A", project=project_a, assignee=employee)
		make_task("TT Sidebar B", project=project_b, assignee=employee)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project_a)
		finally:
			frappe.set_user("Administrator")

		project_names = {p["name"] for p in data["projects"]}
		self.assertIn(project_a, project_names)
		self.assertIn(project_b, project_names)

	def test_employees_empty_when_no_project(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])

		make_task("TT No Project Employees", assignee=employee)

		frappe.set_user(manager)
		try:
			data = get_tracker_data()
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(data["employees"], [])

	def test_employees_scoped_to_selected_project(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		other = ensure_user(OTHER_EMPLOYEE_USER, "Tracker Other", ["Projects User"])
		project_a = ensure_project("TT Roster Project A - scoped test")
		project_b = ensure_project("TT Roster Project B - scoped test")

		make_task("TT Roster A Task", project=project_a, assignee=employee)
		make_task("TT Roster B Task", project=project_b, assignee=other)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project_a)
		finally:
			frappe.set_user("Administrator")

		employee_names = {e["name"] for e in data["employees"]}
		self.assertEqual(employee_names, {employee})

	def test_employee_role_only_sees_self_in_project_employees(self):
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		other = ensure_user(OTHER_EMPLOYEE_USER, "Tracker Other", ["Projects User"])
		project_a = ensure_project("TT Roster Project A - self test")

		make_task("TT Roster Own", project=project_a, assignee=employee)
		make_task("TT Roster Other In Same Project", project=project_a, assignee=other)

		frappe.set_user(employee)
		try:
			data = get_tracker_data(project=project_a)
		finally:
			frappe.set_user("Administrator")

		employee_names = {e["name"] for e in data["employees"]}
		self.assertEqual(employee_names, {employee})


class TestTaskTrackerWorkspaceShortcut(IntegrationTestCase):
	def test_shortcut_link_to_points_at_existing_page(self):
		add_task_tracker_workspace_shortcut()
		self.assertTrue(frappe.db.exists("Page", "task-tracker"))

	def test_creates_shortcut_once_and_is_idempotent(self):
		add_task_tracker_workspace_shortcut()
		count_after_first = frappe.db.count(
			"Workspace Shortcut", {"parent": "Project Management", "link_to": "task-tracker"}
		)
		self.assertEqual(count_after_first, 1)

		add_task_tracker_workspace_shortcut()
		count_after_second = frappe.db.count(
			"Workspace Shortcut", {"parent": "Project Management", "link_to": "task-tracker"}
		)
		self.assertEqual(count_after_second, 1)

		content = json.loads(frappe.db.get_value("Workspace", "Project Management", "content") or "[]")
		shortcut_blocks = [
			b for b in content if b.get("type") == "shortcut" and b.get("data", {}).get("shortcut_name") == "Task Tracker"
		]
		self.assertEqual(len(shortcut_blocks), 1)
