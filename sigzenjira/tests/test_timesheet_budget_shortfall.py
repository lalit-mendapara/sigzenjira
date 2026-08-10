import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from sigzenjira.events.timesheet import check_over_budget
from sigzenjira.tests import ensure_test_employment_type


class TestTimesheetBudgetRemaining(IntegrationTestCase):
	def test_remaining_is_budget_minus_current_actual(self):
		company = frappe.db.get_single_value("Global Defaults", "default_company")

		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "PH7 Remaining Tester",
				"company": company,
				"status": "Active",
				"gender": "Male",
				"date_of_birth": "1995-01-01",
				"date_of_joining": "2024-01-01",
				"employment_type": ensure_test_employment_type(),
			}
		).insert()

		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "PH7 Remaining Task",
				"custom_task_work_item_type": "Task",
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

		warnings = check_over_budget(timesheet.name)
		self.assertEqual(len(warnings), 1)
		w = warnings[0]
		self.assertEqual(w["expected_time"], 5)  # budgeted hours
		self.assertEqual(w["projected_actual"], 8)
		self.assertEqual(w["remaining"], 5)  # nothing logged yet, so full budget was still remaining

	def test_no_warning_when_no_budget_declared_yet(self):
		# Task created via the Task Split "Create Task" escape hatch has
		# expected_time unset (0) until a Projects Manager fills it in later -
		# that's "no budget yet", not "0h budget already exhausted".
		company = frappe.db.get_single_value("Global Defaults", "default_company")

		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "PH7 No Budget Tester",
				"company": company,
				"status": "Active",
				"gender": "Male",
				"date_of_birth": "1995-01-01",
				"date_of_joining": "2024-01-01",
				"employment_type": ensure_test_employment_type(),
			}
		).insert()

		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "PH7 No Budget Task",
				"custom_task_work_item_type": "Task",
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
						"hours": 4,
					}
				],
			}
		).insert()

		self.assertEqual(check_over_budget(timesheet.name), [])
