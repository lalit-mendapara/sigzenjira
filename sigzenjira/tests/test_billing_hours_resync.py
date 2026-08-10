import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from .test_status_cascade import make_task, make_task_under_story
from sigzenjira.tests import ensure_test_employment_type


def make_employee(first_name):
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": first_name,
			"company": frappe.db.get_single_value("Global Defaults", "default_company"),
			"status": "Active",
			"gender": "Male",
			"date_of_birth": "1995-01-01",
			"date_of_joining": "2024-01-01",
			"employment_type": ensure_test_employment_type(),
		}
	).insert()


def make_draft_timesheet(employee, task, hours):
	return frappe.get_doc(
		{
			"doctype": "Timesheet",
			"employee": employee,
			"time_logs": [
				{
					"activity_type": "Execution",
					"task": task,
					"from_time": f"{today()} 10:00:00",
					"hours": hours,
					"is_billable": 1,
				}
			],
		}
	).insert()


class TestBillingHoursResync(IntegrationTestCase):
	def setUp(self):
		self.employee = make_employee("Billing Resync Tester")
		epic = make_task("Resync Epic", "Epic", expected_time=20, is_billable=1)
		story = make_task("Resync Story", "Story", epic.name, expected_time=10, is_billable=1)
		self.task = make_task_under_story(story, "Resync Task", 8, is_billable=1)

	def test_editing_hours_on_a_draft_carries_billing_hours_along(self):
		# The bug: core only defaults billing_hours from hours while
		# billing_hours is 0, so a draft saved at 1h froze the billed amount at
		# 1h even after the row was corrected to 2h.
		timesheet = make_draft_timesheet(self.employee.name, self.task.name, 1)
		self.assertEqual(timesheet.time_logs[0].billing_hours, 1)

		# Same edit the Desk makes: the row is stretched by its end time, and
		# core re-derives hours from the span (timesheet_detail.py:calculate_hours).
		timesheet.time_logs[0].to_time = f"{today()} 12:00:00"
		timesheet.save()

		self.assertEqual(timesheet.time_logs[0].hours, 2)
		self.assertEqual(timesheet.time_logs[0].billing_hours, 2)

		timesheet.submit()
		self.assertEqual(frappe.db.get_value("Task", self.task.name, "custom_task_billable_hours"), 2)
		self.assertEqual(frappe.db.get_value("Task", self.task.name, "custom_task_non_billable_hours"), 0)

	def test_deliberate_partial_billing_survives_an_hours_edit(self):
		# Billing fewer hours than were worked is a supported case
		# (see recompute_actual_time) - the resync must not overwrite it.
		timesheet = make_draft_timesheet(self.employee.name, self.task.name, 4)
		timesheet.time_logs[0].billing_hours = 3
		timesheet.save()
		self.assertEqual(timesheet.time_logs[0].billing_hours, 3)

		timesheet.time_logs[0].to_time = f"{today()} 15:00:00"
		timesheet.save()

		self.assertEqual(timesheet.time_logs[0].hours, 5)
		self.assertEqual(timesheet.time_logs[0].billing_hours, 3)

	def test_editing_billing_hours_alone_is_not_undone(self):
		# hours unchanged, so there is nothing to resync - lowering the billed
		# share by hand must stick.
		timesheet = make_draft_timesheet(self.employee.name, self.task.name, 2)
		timesheet.time_logs[0].billing_hours = 1
		timesheet.save()

		self.assertEqual(timesheet.time_logs[0].billing_hours, 1)
