import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from .test_status_cascade import make_task, make_task_under_story


class TestCostingRollup(IntegrationTestCase):
	def test_subtask_costing_rolls_up_to_task_story_and_epic(self):
		company = frappe.db.get_single_value("Global Defaults", "default_company")

		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "PH7 Costing Tester",
				"company": company,
				"status": "Active",
				"gender": "Male",
				"date_of_birth": "1995-01-01",
				"date_of_joining": "2024-01-01",
			}
		).insert()

		activity_cost = frappe.get_doc(
			{
				"doctype": "Activity Cost",
				"employee": employee.name,
				"activity_type": "Execution",
				"costing_rate": 100,
				"billing_rate": 150,
			}
		).insert()

		epic = make_task("PH7 Costing Epic", "Epic", expected_time=20, is_billable=1)
		story = make_task("PH7 Costing Story", "Story", epic.name, expected_time=10, is_billable=1)
		task = make_task_under_story(story, "PH7 Costing Task", 5, is_billable=1)
		sub_task = make_task("PH7 Costing Sub-task", "Sub-task", task.name, is_billable=1)

		timesheet = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"employee": employee.name,
				"time_logs": [
					{
						"activity_type": "Execution",
						"task": sub_task.name,
						"from_time": f"{today()} 09:00:00",
						"hours": 2,
						"is_billable": 1,
					}
				],
			}
		).insert()
		timesheet.submit()

		# 2 hours * costing_rate 100 = 200, 2 hours * billing_rate 150 = 300,
		# logged against the Sub-task, must roll up to Task, Story and Epic
		# exactly like actual_time does.
		for name in (task.name, story.name, epic.name):
			self.assertEqual(frappe.db.get_value("Task", name, "total_costing_amount"), 200)
			self.assertEqual(frappe.db.get_value("Task", name, "total_billing_amount"), 300)

		timesheet.cancel()

		for name in (task.name, story.name, epic.name):
			self.assertEqual(frappe.db.get_value("Task", name, "total_costing_amount"), 0)
			self.assertEqual(frappe.db.get_value("Task", name, "total_billing_amount"), 0)

		activity_cost.delete()
