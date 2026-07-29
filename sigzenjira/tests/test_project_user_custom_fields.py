import frappe
from frappe.tests import IntegrationTestCase


class TestProjectUserCustomFields(IntegrationTestCase):
	def test_project_user_flag_fields_exist(self):
		for fieldname in ("custom_allocate_hours", "custom_assign_users", "custom_approve_extra_hours"):
			self.assertEqual(
				frappe.db.get_value("Custom Field", {"dt": "Project User", "fieldname": fieldname}, "fieldtype"),
				"Check",
			)

	def test_project_extra_hours_approver_field_removed(self):
		self.assertFalse(
			frappe.db.exists("Custom Field", {"dt": "Project", "fieldname": "custom_extra_hours_approver"})
		)
		self.assertFalse(frappe.db.has_column("Project", "custom_extra_hours_approver"))
