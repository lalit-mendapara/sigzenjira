import json

import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.install import create_pm_dashboard_reports, create_pm_dashboard_cards, create_pm_dashboard_charts, create_pm_dashboard


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


class TestPMDashboardCharts(IntegrationTestCase):
	def setUp(self):
		# Create a Task record so group-by charts have data to work with
		if not frappe.db.exists("Task", {"subject": "Test Task for Dashboard Charts"}):
			frappe.get_doc({
				"doctype": "Task",
				"subject": "Test Task for Dashboard Charts",
				"status": "Open",
				"custom_work_item_type": "Task",
			}).insert(ignore_permissions=True)

	def test_creates_eight_charts_with_correct_roles(self):
		create_pm_dashboard_charts()

		manager_only = [
			"PM Tasks by Status",
			"PM Tasks by Work Item Type",
			"PM Issues by Status",
			"PM Workload Distribution",
			"PM Hours Logged Trend",
		]
		my_work = [
			"PM My Tasks by Status",
			"PM My Issues by Status",
			"PM My Hours Trend",
		]

		for name in manager_only:
			chart = frappe.get_doc("Dashboard Chart", name)
			self.assertEqual([r.role for r in chart.roles], ["Projects Manager"])

		for name in my_work:
			chart = frappe.get_doc("Dashboard Chart", name)
			self.assertEqual(sorted(r.role for r in chart.roles), ["Projects Manager", "Projects User"])

	def test_chart_config_renders_without_error(self):
		create_pm_dashboard_charts()
		from frappe.desk.doctype.dashboard_chart.dashboard_chart import get as get_chart_config

		config = get_chart_config(chart_name="PM Tasks by Status")
		self.assertIsInstance(config, dict)

	def test_charts_idempotent_on_rerun(self):
		create_pm_dashboard_charts()
		count_before = frappe.db.count("Dashboard Chart", {"chart_name": ["like", "PM %"]})
		create_pm_dashboard_charts()
		count_after = frappe.db.count("Dashboard Chart", {"chart_name": ["like", "PM %"]})
		self.assertEqual(count_before, count_after)


class TestPMDashboard(IntegrationTestCase):
	def test_dashboard_links_all_cards_and_charts(self):
		create_pm_dashboard()

		dashboard = frappe.get_doc("Dashboard", "PM Project Management Dashboard")
		self.assertEqual(len(dashboard.cards), 12)
		self.assertEqual(len(dashboard.charts), 8)

		card_names = {row.card for row in dashboard.cards}
		self.assertIn("PM Open Tasks", card_names)
		self.assertIn("PM My Open Tasks", card_names)

		chart_names = {row.chart for row in dashboard.charts}
		self.assertIn("PM Tasks by Status", chart_names)
		self.assertIn("PM My Tasks by Status", chart_names)

	def test_workspace_shortcut_added_once(self):
		create_pm_dashboard()
		ws = frappe.get_doc("Workspace", "Project Management")
		matches = [row for row in ws.shortcuts if row.link_to == "PM Project Management Dashboard"]
		self.assertEqual(len(matches), 1)
		self.assertEqual(matches[0].type, "Dashboard")

		create_pm_dashboard()  # re-run must not duplicate the shortcut
		ws_again = frappe.get_doc("Workspace", "Project Management")
		matches_again = [row for row in ws_again.shortcuts if row.link_to == "PM Project Management Dashboard"]
		self.assertEqual(len(matches_again), 1)

	def test_workspace_content_block_added_once(self):
		create_pm_dashboard()

		def shortcut_blocks():
			content = json.loads(frappe.db.get_value("Workspace", "Project Management", "content") or "[]")
			return [
				block
				for block in content
				if block.get("type") == "shortcut" and block.get("data", {}).get("shortcut_name") == "PM Dashboard"
			]

		self.assertEqual(len(shortcut_blocks()), 1)

		create_pm_dashboard()  # re-run must not duplicate the content block
		self.assertEqual(len(shortcut_blocks()), 1)
