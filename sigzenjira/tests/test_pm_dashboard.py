import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.install import create_pm_dashboard_reports


class TestPMDashboardReports(IntegrationTestCase):
	def test_creates_six_manager_query_reports(self):
		create_pm_dashboard_reports()

		expected = [
			"PM Open Tasks Count",
			"PM Overdue Tasks Count",
			"PM Pending Extra Hours Count",
			"PM Extra Hours Approved Sum",
			"PM Hours This Week Sum",
			"PM Open Issues Count",
		]
		for name in expected:
			self.assertTrue(frappe.db.exists("Report", name), f"missing report {name}")

		for name in expected:
			report = frappe.get_doc("Report", name)
			self.assertEqual(report.report_type, "Query Report")
			roles = [r.role for r in report.roles]
			self.assertEqual(roles, ["Projects Manager"])
			row = frappe.db.sql(report.query, as_dict=True)
			self.assertEqual(len(row), 1)
			self.assertIn("value", row[0])
			self.assertGreaterEqual(row[0]["value"] or 0, 0)

	def test_idempotent_on_rerun(self):
		create_pm_dashboard_reports()
		count_before = frappe.db.count("Report", {"report_name": ["like", "PM %"]})
		create_pm_dashboard_reports()
		count_after = frappe.db.count("Report", {"report_name": ["like", "PM %"]})
		self.assertEqual(count_before, count_after)
