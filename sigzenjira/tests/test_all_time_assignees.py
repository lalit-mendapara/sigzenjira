import frappe
from frappe.desk.form import assign_to
from frappe.tests import IntegrationTestCase
from frappe.utils import get_fullname

from .test_status_cascade import make_task


class TestAllTimeAssignees(IntegrationTestCase):
	def make_user(self, email, first_name):
		if frappe.db.exists("User", email):
			return email

		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": first_name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		return email

	def test_assign_to_keeps_every_assignee_after_core_clears_assign(self):
		one = self.make_user("assignee.one@sigzenjira.test", "Assignee One")
		two = self.make_user("assignee.two@sigzenjira.test", "Assignee Two")

		task = make_task("All-time assignee Epic", "Epic", expected_time=5)

		assign_to.add({"doctype": "Task", "name": task.name, "assign_to": [one, two]})
		self.assertEqual(
			frappe.db.get_value("Task", task.name, "custom_task_assign_to"),
			f"{get_fullname(one)}, {get_fullname(two)}",
		)

		# Completing one and removing the other empties core's _assign entirely.
		assign_to.set_status("Task", task.name, assign_to=one, status="Closed", ignore_permissions=True)
		assign_to._remove("Task", task.name, two, ignore_permissions=True)

		self.assertFalse(frappe.db.get_value("Task", task.name, "_assign"))
		self.assertEqual(
			frappe.db.get_value("Task", task.name, "custom_task_assign_to"),
			f"{get_fullname(one)}, {get_fullname(two)}",
		)
		# What the list view's standard filter matches on.
		self.assertIn(
			task.name,
			frappe.get_all(
				"Task", filters={"custom_task_assign_to": ("like", f"%{get_fullname(two)}%")}, pluck="name"
			),
		)

		# Re-assigning an existing name must not duplicate it.
		assign_to.add({"doctype": "Task", "name": task.name, "assign_to": [one]})
		self.assertEqual(
			frappe.db.get_value("Task", task.name, "custom_task_assign_to"),
			f"{get_fullname(one)}, {get_fullname(two)}",
		)

	def test_manager_pruning_survives_the_next_todo_save(self):
		one = self.make_user("assignee.four@sigzenjira.test", "Assignee Four")
		two = self.make_user("assignee.five@sigzenjira.test", "Assignee Five")

		task = make_task("Pruned assignee Epic", "Epic", expected_time=5)
		assign_to.add({"doctype": "Task", "name": task.name, "assign_to": [one, two]})
		assign_to.set_status("Task", task.name, assign_to=one, status="Closed", ignore_permissions=True)

		# What a Projects Manager does by hand: drop a name that is no longer in
		# core's Assigned To.
		frappe.db.set_value("Task", task.name, "custom_task_assign_to", get_fullname(two))

		# Any later ToDo save on the doc must not resurrect the pruned name.
		assign_to.set_status("Task", task.name, assign_to=two, status="Closed", ignore_permissions=True)

		self.assertEqual(
			frappe.db.get_value("Task", task.name, "custom_task_assign_to"), get_fullname(two)
		)

	def test_issue_tracks_assignees_too(self):
		one = self.make_user("assignee.three@sigzenjira.test", "Assignee Three")

		issue = frappe.get_doc({"doctype": "Issue", "subject": "All-time assignee Issue"}).insert()

		assign_to.add({"doctype": "Issue", "name": issue.name, "assign_to": [one]})
		assign_to._remove("Issue", issue.name, one, ignore_permissions=True)

		self.assertEqual(
			frappe.db.get_value("Issue", issue.name, "custom_issue_assign_to"), get_fullname(one)
		)
