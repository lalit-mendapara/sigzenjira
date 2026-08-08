import json

import frappe

ORG_ROLES = ["Projects Manager"]
MY_WORK_ROLES = ["Projects User", "Projects Manager"]


def get_query_reports():
	return [
		{
			"report_name": "Open Tasks Count",
			"ref_doctype": "Task",
			"query": (
				"select count(*) as value from `tabTask` "
				"where status in ('Open', 'Working', 'Pending Review', 'Blocked')"
			),
		},
		{
			"report_name": "Overdue Tasks Count",
			"ref_doctype": "Task",
			"query": "select count(*) as value from `tabTask` where status = 'Overdue'",
		},
		{
			"report_name": "Pending Extra Hours Count",
			"ref_doctype": "Additional Hours Request",
			"query": (
				"select count(*) as value from `tabAdditional Hours Request` "
				"where status = 'Pending'"
			),
		},
		{
			"report_name": "Extra Hours Approved Sum",
			"ref_doctype": "Additional Hours Request",
			"query": (
				"select coalesce(sum(additional_hours_requested), 0) as value "
				"from `tabAdditional Hours Request` where status = 'Approved'"
			),
		},
		{
			"report_name": "Hours This Week Sum",
			"ref_doctype": "Timesheet",
			"query": (
				"select coalesce(sum(total_hours), 0) as value from `tabTimesheet` "
				"where docstatus = 1 and yearweek(start_date, 1) = yearweek(curdate(), 1)"
			),
		},
		{
			"report_name": "Open Issues Count",
			"ref_doctype": "Issue",
			"query": (
				"select count(*) as value from `tabIssue` "
				"where status not in ('Resolved', 'Closed')"
			),
		},
	]


def get_number_cards():
	me_assign_filter = lambda doctype: [[doctype, "_assign", "like", "'%' + frappe.session.user + '%'"]]

	return [
		# Manager-only, Report-backed (roles come from the backing Report)
		{
			"label": "Open Tasks",
			"type": "Report",
			"report_name": "Open Tasks Count",
			"report_field": "value",
			"report_function": "Sum",
		},
		{
			"label": "Task Overdue Count",
			"type": "Report",
			"report_name": "Overdue Tasks Count",
			"report_field": "value",
			"report_function": "Sum",
		},
		{
			"label": "Pending Extra Hours Approvals",
			"type": "Report",
			"report_name": "Pending Extra Hours Count",
			"report_field": "value",
			"report_function": "Sum",
		},
		{
			"label": "Extra Hours Approved",
			"type": "Report",
			"report_name": "Extra Hours Approved Sum",
			"report_field": "value",
			"report_function": "Sum",
		},
		{
			"label": "Hours Logged This Week",
			"type": "Report",
			"report_name": "Hours This Week Sum",
			"report_field": "value",
			"report_function": "Sum",
		},
		{
			"label": "Open Issues",
			"type": "Report",
			"report_name": "Open Issues Count",
			"report_field": "value",
			"report_function": "Sum",
		},
		# "My work" — Document Type, visible to everyone, scoped to the viewer
		{
			"label": "My Open Tasks",
			"type": "Document Type",
			"document_type": "Task",
			"function": "Count",
			"filters": [["Task", "status", "not in", ["Completed", "Cancelled"]]],
			"dynamic_filters": me_assign_filter("Task"),
		},
		{
			"label": "My Overdue Tasks",
			"type": "Document Type",
			"document_type": "Task",
			"function": "Count",
			"filters": [["Task", "status", "=", "Overdue"]],
			"dynamic_filters": me_assign_filter("Task"),
		},
		{
			"label": "My Hours This Week",
			"type": "Document Type",
			"document_type": "Timesheet",
			"function": "Sum",
			"aggregate_function_based_on": "total_hours",
			"filters": [["Timesheet", "docstatus", "=", 1]],
			"dynamic_filters": [
				["Timesheet", "owner", "=", "frappe.session.user"],
				["Timesheet", "start_date", ">=", "frappe.datetime.week_start()"],
			],
		},
		{
			"label": "My Pending Extra Hours Requests",
			"type": "Document Type",
			"document_type": "Additional Hours Request",
			"function": "Count",
			"filters": [["Additional Hours Request", "status", "=", "Pending"]],
			"dynamic_filters": [["Additional Hours Request", "requested_by", "=", "frappe.session.user"]],
		},
		{
			"label": "My Approved Extra Hours",
			"type": "Document Type",
			"document_type": "Additional Hours Request",
			"function": "Sum",
			"aggregate_function_based_on": "additional_hours_requested",
			"filters": [["Additional Hours Request", "status", "=", "Approved"]],
			"dynamic_filters": [["Additional Hours Request", "requested_by", "=", "frappe.session.user"]],
		},
		{
			"label": "My Open Issues",
			"type": "Document Type",
			"document_type": "Issue",
			"function": "Count",
			"filters": [["Issue", "status", "not in", ["Resolved", "Closed"]]],
			"dynamic_filters": me_assign_filter("Issue"),
		},
	]


def get_dashboard_charts():
	me_assign_filter = lambda doctype: [[doctype, "_assign", "like", "'%' + frappe.session.user + '%'"]]

	return [
		{
			"chart_name": "Tasks by Status",
			"chart_type": "Group By",
			"document_type": "Task",
			"group_by_based_on": "status",
			"group_by_type": "Count",
			"type": "Donut",
			"roles": ORG_ROLES,
			"filters": [],
		},
		{
			"chart_name": "Tasks by Work Item Type Breakdown",
			"chart_type": "Group By",
			"document_type": "Task",
			"group_by_based_on": "custom_task_work_item_type",
			"group_by_type": "Count",
			"type": "Bar",
			"roles": ORG_ROLES,
			"filters": [],
		},
		{
			"chart_name": "Issues by Status",
			"chart_type": "Group By",
			"document_type": "Issue",
			"group_by_based_on": "status",
			"group_by_type": "Count",
			"type": "Donut",
			"roles": ORG_ROLES,
			"filters": [],
		},
		{
			"chart_name": "Workload Distribution",
			"chart_type": "Group By",
			"document_type": "ToDo",
			"group_by_based_on": "allocated_to",
			"group_by_type": "Count",
			"type": "Bar",
			"roles": ORG_ROLES,
			"filters": [["ToDo", "reference_type", "=", "Task"], ["ToDo", "status", "=", "Open"]],
		},
		{
			"chart_name": "Hours Logged Trend",
			"chart_type": "Sum",
			"document_type": "Timesheet",
			"value_based_on": "total_hours",
			"timeseries": 1,
			"based_on": "start_date",
			"time_interval": "Weekly",
			"timespan": "Last Quarter",
			"type": "Line",
			"roles": ORG_ROLES,
			"filters": [["Timesheet", "docstatus", "=", 1]],
		},
		{
			"chart_name": "My Tasks by Status",
			"chart_type": "Group By",
			"document_type": "Task",
			"group_by_based_on": "status",
			"group_by_type": "Count",
			"type": "Donut",
			"roles": MY_WORK_ROLES,
			"filters": [],
			"dynamic_filters": me_assign_filter("Task"),
		},
		{
			"chart_name": "My Issues by Status",
			"chart_type": "Group By",
			"document_type": "Issue",
			"group_by_based_on": "status",
			"group_by_type": "Count",
			"type": "Donut",
			"roles": MY_WORK_ROLES,
			"filters": [],
			"dynamic_filters": me_assign_filter("Issue"),
		},
		{
			"chart_name": "My Hours Trend",
			"chart_type": "Sum",
			"document_type": "Timesheet",
			"value_based_on": "total_hours",
			"timeseries": 1,
			"based_on": "start_date",
			"time_interval": "Weekly",
			"timespan": "Last Quarter",
			"type": "Line",
			"roles": MY_WORK_ROLES,
			"filters": [["Timesheet", "docstatus", "=", 1]],
			"dynamic_filters": [["Timesheet", "owner", "=", "frappe.session.user"]],
		},
	]


def get_dashboard():
	trend_charts = {"Hours Logged Trend", "My Hours Trend"}
	card_names = [card["label"] for card in get_number_cards()]
	chart_names = [chart["chart_name"] for chart in get_dashboard_charts()]

	return {
		"dashboard_name": "Project Management Dashboard",
		"cards": [{"card": name} for name in card_names],
		"charts": [
			{"chart": name, "width": "Full" if name in trend_charts else "Half"} for name in chart_names
		],
	}


def get_workspace_shortcut():
	return {
		"label": "Dashboard",
		"type": "Dashboard",
		"link_to": "Project Management Dashboard",
	}


def create_pm_dashboard_reports():
	for report in get_query_reports():
		if frappe.db.exists("Report", report["report_name"]):
			continue
		frappe.get_doc(
			{
				"doctype": "Report",
				"report_name": report["report_name"],
				"ref_doctype": report["ref_doctype"],
				"report_type": "Query Report",
				"is_standard": "No",
				"query": report["query"],
				"roles": [{"role": "Projects Manager"}],
			}
		).insert(ignore_permissions=True)


def create_pm_dashboard_cards():
	for card in get_number_cards():
		if frappe.db.exists("Number Card", card["label"]):
			continue
		doc_dict = {"doctype": "Number Card", **card}
		if "filters" in doc_dict:
			doc_dict["filters_json"] = frappe.as_json(doc_dict.pop("filters"))
		if "dynamic_filters" in doc_dict:
			doc_dict["dynamic_filters_json"] = frappe.as_json(doc_dict.pop("dynamic_filters"))
		frappe.get_doc(doc_dict).insert(ignore_permissions=True)


def create_pm_dashboard_charts():
	for chart in get_dashboard_charts():
		if frappe.db.exists("Dashboard Chart", chart["chart_name"]):
			continue
		doc_dict = {"doctype": "Dashboard Chart", **chart}
		doc_dict["roles"] = [{"role": role} for role in doc_dict.pop("roles")]
		doc_dict["filters_json"] = frappe.as_json(doc_dict.pop("filters", []))
		if "dynamic_filters" in doc_dict:
			doc_dict["dynamic_filters_json"] = frappe.as_json(doc_dict.pop("dynamic_filters"))
		frappe.get_doc(doc_dict).insert(ignore_permissions=True)


def create_pm_dashboard():
	create_pm_dashboard_reports()
	create_pm_dashboard_cards()
	create_pm_dashboard_charts()

	dashboard = get_dashboard()
	if not frappe.db.exists("Dashboard", dashboard["dashboard_name"]):
		frappe.get_doc({"doctype": "Dashboard", **dashboard}).insert(ignore_permissions=True)

	add_pm_dashboard_workspace_shortcut()


def add_pm_dashboard_workspace_shortcut():
	# Inserting the child row directly via frappe.new_doc() (not via ws.append() +
	# ws.save()) because the existing "Project Management" workspace already has a
	# broken shortcut (Task Hour Budget Overrun -> a Report that does not exist on
	# this site), which causes ws.save() to fail with LinkValidationError. This
	# approach also ensures that function is idempotent and never disturbs the
	# pre-existing workspace state.
	shortcut = get_workspace_shortcut()
	# Check if shortcut already exists
	if not frappe.db.exists(
		"Workspace Shortcut", {"parent": "Project Management", "link_to": shortcut["link_to"]}
	):
		# Insert shortcut row as a child document
		doc = frappe.new_doc("Workspace Shortcut")
		doc.update(
			{
				"parent": "Project Management",
				"parenttype": "Workspace",
				"parentfield": "shortcuts",
				**shortcut,
			}
		)
		doc.insert(ignore_permissions=True)

	# The shortcuts child table alone doesn't render anything - Frappe's workspace
	# UI builds the page layout from the `content` field (EditorJS-style JSON
	# blocks) and only shows a "shortcut" block if `content` has one whose
	# `shortcut_name` matches a row in `shortcuts` by label (see
	# frappe/public/js/frappe/views/workspace/blocks/block.js make()). Written via
	# frappe.db.set_value for the same reason as above: ws.save() would crash on
	# the pre-existing broken "Task Hour Budget Overrun" shortcut link.
	content = json.loads(frappe.db.get_value("Workspace", "Project Management", "content") or "[]")
	already_has_block = any(
		block.get("type") == "shortcut" and block.get("data", {}).get("shortcut_name") == shortcut["label"]
		for block in content
	)
	if not already_has_block:
		content.append(
			{
				"id": "sigzenjiraPmDashboardShortcut",
				"type": "shortcut",
				"data": {"shortcut_name": shortcut["label"], "col": 4},
			}
		)
		frappe.db.set_value("Workspace", "Project Management", "content", json.dumps(content))
