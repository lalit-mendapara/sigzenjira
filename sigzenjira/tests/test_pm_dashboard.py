import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.install import create_pm_dashboard_reports, create_pm_dashboard_cards


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


class TestPMDashboardCards(IntegrationTestCase):
	def test_creates_twelve_number_cards(self):
		create_pm_dashboard_reports()
		create_pm_dashboard_cards()

		report_backed = [
			"PM Open Tasks",
			"PM Overdue Tasks",
			"PM Pending Extra Hours Approvals",
			"PM Extra Hours Approved",
			"PM Hours Logged This Week",
			"PM Open Issues",
		]
		doctype_backed = [
			"PM My Open Tasks",
			"PM My Overdue Tasks",
			"PM My Hours This Week",
			"PM My Pending Extra Hours Requests",
			"PM My Approved Extra Hours",
			"PM My Open Issues",
		]

		for label in report_backed:
			card = frappe.get_doc("Number Card", label)
			self.assertEqual(card.type, "Report")
			self.assertTrue(frappe.db.exists("Report", card.report_name))

		for label in doctype_backed:
			card = frappe.get_doc("Number Card", label)
			self.assertEqual(card.type, "Document Type")
			self.assertTrue(card.document_type)

	def test_my_open_tasks_result_is_computable(self):
		create_pm_dashboard_reports()
		create_pm_dashboard_cards()
		from frappe.desk.doctype.number_card.number_card import get_result

		card = frappe.get_doc("Number Card", "PM My Open Tasks").as_dict()
		result = get_result(doc=frappe.as_json(card), filters=card.get("filters_json"))
		self.assertGreaterEqual(result, 0)

	def test_cards_idempotent_on_rerun(self):
		create_pm_dashboard_reports()
		create_pm_dashboard_cards()
		count_before = frappe.db.count("Number Card", {"label": ["like", "PM %"]})
		create_pm_dashboard_cards()
		count_after = frappe.db.count("Number Card", {"label": ["like", "PM %"]})
		self.assertEqual(count_before, count_after)
