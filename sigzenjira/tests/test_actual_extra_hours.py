import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today


class TestActualExtraHours(IntegrationTestCase):
	def test_recompute_actual_time_sets_actual_extra_hours(self):
		company = frappe.db.get_single_value("Global Defaults", "default_company")

		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "PH7 Extra Hours Tester",
				"company": company,
				"status": "Active",
				"gender": "Male",
				"date_of_birth": "1995-01-01",
				"date_of_joining": "2024-01-01",
			}
		).insert()

		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "PH7 Extra Hours Task",
				"custom_work_item_type": "Task",
				"expected_time": 5,
			}
		).insert()

		timesheet = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"employee": employee.name,
				"time_logs": [
					{
						"activity_type": "Execution",
						"task": task.name,
						"from_time": f"{today()} 09:00:00",
						"hours": 8,
					}
				],
			}
		).insert()
		timesheet.submit()

		# over budget: 8 actual - 5 expected = +3
		self.assertEqual(frappe.db.get_value("Task", task.name, "custom_actual_extra_hours"), 3)

		timesheet.cancel()

		# back to no hours logged: 0 actual - 5 expected = -5
		self.assertEqual(frappe.db.get_value("Task", task.name, "custom_actual_extra_hours"), -5)

	def test_plain_save_recomputes_when_expected_time_changes(self):
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "PH7 Extra Hours Plain Save Task",
				"custom_work_item_type": "Task",
				"expected_time": 5,
			}
		).insert()
		frappe.db.set_value("Task", task.name, "actual_time", 10, update_modified=False)

		task.reload()
		task.expected_time = 4
		task.save()

		self.assertEqual(task.custom_actual_extra_hours, 6)


if __name__ == "__main__":
	import unittest

	unittest.main()
