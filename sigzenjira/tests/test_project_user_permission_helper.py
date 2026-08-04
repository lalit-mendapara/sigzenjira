import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.custom.permissions import user_is_project_member
from sigzenjira.custom.project_user import get_project_approvers, user_has_project_flag

FLAG_EMPLOYEE = "test_pu_helper_employee@example.com"
FLAG_SYSMAN = "test_pu_helper_sysman@example.com"


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


def make_project(name, user_rows=None):
	if frappe.db.exists("Project", name):
		frappe.delete_doc("Project", name, force=True, ignore_permissions=True)
	project = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": name,
			"users": [
				{
					"user": row["user"],
					"custom_allocate_hours": row.get("custom_allocate_hours", 0),
					"custom_assign_users": row.get("custom_assign_users", 0),
					"custom_approve_extra_hours": row.get("custom_approve_extra_hours", 0),
				}
				for row in (user_rows or [])
			],
		}
	)
	project.insert(ignore_permissions=True)
	return project


class TestProjectUserPermissionHelper(IntegrationTestCase):
	def test_administrator_always_bypasses(self):
		self.assertTrue(user_has_project_flag(None, "custom_allocate_hours", user="Administrator"))

	def test_system_manager_always_bypasses(self):
		user = ensure_user(FLAG_SYSMAN, "PU Helper Sysman", ["System Manager"])
		self.assertTrue(user_has_project_flag("Any Nonexistent Project", "custom_allocate_hours", user=user))

	def test_no_project_denies_non_privileged_user(self):
		user = ensure_user(FLAG_EMPLOYEE, "PU Helper Employee", ["Employee"])
		self.assertFalse(user_has_project_flag(None, "custom_allocate_hours", user=user))

	def test_flagged_project_user_passes_only_matching_flag(self):
		user = ensure_user(FLAG_EMPLOYEE, "PU Helper Employee", ["Employee"])
		project = make_project(
			"PU Helper Project", [{"user": user, "custom_allocate_hours": 1, "custom_assign_users": 0}]
		)
		self.assertTrue(user_has_project_flag(project.name, "custom_allocate_hours", user=user))
		self.assertFalse(user_has_project_flag(project.name, "custom_assign_users", user=user))

	def test_get_project_approvers_returns_only_flagged_rows(self):
		user = ensure_user(FLAG_EMPLOYEE, "PU Helper Employee", ["Employee"])
		project = make_project(
			"PU Helper Approvers Project",
			[
				{"user": user, "custom_approve_extra_hours": 1},
				{"user": "Administrator", "custom_approve_extra_hours": 0},
			],
		)
		self.assertEqual(get_project_approvers(project.name), [user])

	def test_get_project_approvers_empty_for_no_project(self):
		self.assertEqual(get_project_approvers(None), [])


PO_USER = "test_pu_helper_po@example.com"


class TestProjectScopeBypass(IntegrationTestCase):
	def test_product_owner_bypasses_project_scope(self):
		# Product Owner is already privileged enough to set Billable and Work
		# Item Type (WORK_ITEM_TYPE_PRIVILEGED_ROLES in custom/task.py); the
		# bypass set is being brought in line with that.
		if not frappe.db.exists("Role", "Product Owner"):
			frappe.get_doc({"doctype": "Role", "role_name": "Product Owner"}).insert(ignore_permissions=True)

		user = ensure_user(PO_USER, "PU Helper PO", ["Product Owner"])
		project = make_project("PU Helper PO Project", [{"user": "Administrator"}])

		# Not a Project User on it, and still sees it.
		self.assertTrue(user_is_project_member(project.name, user=user))

	def test_plain_employee_still_scoped(self):
		# Guard against the bypass set being widened past what was asked for.
		user = ensure_user(FLAG_EMPLOYEE, "PU Helper Employee", ["Employee"])
		project = make_project("PU Helper Scoped Project", [{"user": "Administrator"}])
		self.assertFalse(user_is_project_member(project.name, user=user))
