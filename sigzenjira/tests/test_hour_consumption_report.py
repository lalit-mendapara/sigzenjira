import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.sigzenjira.report.project_hour_consumption.project_hour_consumption import execute

from .test_status_cascade import make_task

REPORT_PO = "test_hcr_po@example.com"
REPORT_OUTSIDER = "test_hcr_outsider@example.com"


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


def make_billable_project(name):
	# Project autonames off `naming_series` (PROJ-####), not project_name, so
	# the exists-check has to look up the docname via project_name - checking
	# by `name` directly never matches and IntegrationTestCase only rolls back
	# once per class, not per test, so a stale row from an earlier test method
	# in this run would otherwise collide on project_name's unique constraint.
	existing = frappe.db.exists("Project", {"project_name": name})
	if existing:
		frappe.delete_doc("Project", existing, force=True, ignore_permissions=True)
	return frappe.get_doc(
		{"doctype": "Project", "project_name": name, "custom_is_billable": 1}
	).insert(ignore_permissions=True)


class TestHourConsumptionReportGuards(IntegrationTestCase):
	def setUp(self):
		self.project = make_billable_project("HCR Guards Project")

	def test_missing_project_throws(self):
		with self.assertRaises(frappe.ValidationError):
			execute({})

	def test_outsider_gets_permission_error(self):
		user = ensure_user(REPORT_OUTSIDER, "HCR Outsider", ["Projects User"])
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				execute({"project": self.project.name})
		finally:
			frappe.set_user("Administrator")

	def test_story_from_another_project_throws(self):
		other = make_billable_project("HCR Guards Other Project")
		epic = make_task("HCR Guards Epic", "Epic", project=other.name, is_billable=1)
		story = make_task("HCR Guards Story", "Story", epic.name, project=other.name, is_billable=1)

		with self.assertRaises(frappe.ValidationError):
			execute({"project": self.project.name, "story": story.name})

	def test_inverted_date_range_throws(self):
		with self.assertRaises(frappe.ValidationError):
			execute({"project": self.project.name, "from_date": "2026-07-31", "to_date": "2026-07-01"})

	def test_product_owner_reads_a_project_they_are_not_on(self):
		# The bypass widening from Task 1, asserted at the report's own door.
		if not frappe.db.exists("Role", "Product Owner"):
			frappe.get_doc({"doctype": "Role", "role_name": "Product Owner"}).insert(ignore_permissions=True)

		user = ensure_user(REPORT_PO, "HCR Product Owner", ["Projects User", "Product Owner"])
		frappe.set_user(user)
		try:
			_columns, data, _message, _chart, _summary = execute({"project": self.project.name})
			self.assertEqual(data, [])
		finally:
			frappe.set_user("Administrator")

	def test_valid_filters_return_columns_and_no_rows(self):
		columns, data, message, chart, summary = execute({"project": self.project.name})
		self.assertEqual(data, [])
		self.assertEqual([c["fieldname"] for c in columns][:3], ["work_item", "subject", "work_item_type"])
