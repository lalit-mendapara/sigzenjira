import frappe
from frappe.tests import IntegrationTestCase

# No IGNORE_TEST_RECORD_DEPENDENCIES here: it only works for test modules inside
# a doctype folder (frappe/tests/classes/integration_test_case.py:59 raises
# NotImplementedError otherwise - see test_work_board.py for the same note).
# Not needed anyway - this test only inspects Custom Field/meta definitions,
# it never creates a Project/Issue/Employee/Timesheet document.


class TestBillableFields(IntegrationTestCase):
	def test_billable_custom_fields_exist(self):
		for doctype in ("Project", "Issue", "Task"):
			self.assertTrue(
				frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": "custom_is_billable"}),
				f"custom_is_billable missing on {doctype}",
			)

	def test_billable_fields_are_checks_defaulting_to_zero(self):
		for doctype in ("Project", "Issue", "Task"):
			meta_field = frappe.get_meta(doctype).get_field("custom_is_billable")
			self.assertEqual(meta_field.fieldtype, "Check")
			self.assertEqual(meta_field.default, "0")

	def test_task_split_has_is_billable_column(self):
		meta_field = frappe.get_meta("Task Split").get_field("is_billable")
		self.assertIsNotNone(meta_field)
		self.assertEqual(meta_field.fieldtype, "Check")
		self.assertEqual(meta_field.in_list_view, 1)
