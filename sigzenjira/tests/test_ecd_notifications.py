import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.permission.project_user import ecd_alert_manager_emails

MANAGER = "test_ecd_manager@example.com"
MEMBER = "test_ecd_member@example.com"


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
			# Mandatory on this bench via a Property Setter, not app code.
			"project_type": "Internal",
			"users": [
				{
					"user": row["user"],
					# Every Check field set explicitly - one omitted from the dict
					# comes back as 1, not 0.
					"custom_project_user_allocate_hours": row.get("custom_project_user_allocate_hours", 0),
					"custom_project_user_assign_users": row.get("custom_project_user_assign_users", 0),
					"custom_project_user_approve_extra_hours": row.get(
						"custom_project_user_approve_extra_hours", 0
					),
				}
				for row in (user_rows or [])
			],
		}
	)
	project.insert(ignore_permissions=True)
	return project


class TestEcdAlertManagerEmails(IntegrationTestCase):
	def test_returns_only_flagged_project_users(self):
		manager = ensure_user(MANAGER, "ECD Manager", ["Employee"])
		member = ensure_user(MEMBER, "ECD Member", ["Employee"])
		project = make_project(
			"ECD Alert CC Project",
			[
				{"user": manager, "custom_project_user_approve_extra_hours": 1},
				{"user": member, "custom_project_user_approve_extra_hours": 0},
			],
		)
		self.assertEqual(ecd_alert_manager_emails(project.name), manager)

	def test_joins_multiple_managers_with_commas(self):
		manager = ensure_user(MANAGER, "ECD Manager", ["Employee"])
		project = make_project(
			"ECD Alert CC Multi Project",
			[
				{"user": manager, "custom_project_user_approve_extra_hours": 1},
				{"user": "Administrator", "custom_project_user_approve_extra_hours": 1},
			],
		)
		self.assertCountEqual(ecd_alert_manager_emails(project.name).split(","), [manager, "Administrator"])

	def test_empty_string_for_no_project(self):
		# Tasks may have no Project at all - the cc template must render to
		# nothing rather than blowing up the whole alert.
		self.assertEqual(ecd_alert_manager_emails(None), "")

	def test_empty_string_for_project_with_no_approvers(self):
		member = ensure_user(MEMBER, "ECD Member", ["Employee"])
		project = make_project(
			"ECD Alert CC Empty Project",
			[{"user": member, "custom_project_user_approve_extra_hours": 0}],
		)
		self.assertEqual(ecd_alert_manager_emails(project.name), "")
