ORG_ROLES = ["Projects Manager"]
MY_WORK_ROLES = ["Projects User", "Projects Manager"]


def get_query_reports():
	return [
		{
			"report_name": "PM Open Tasks Count",
			"ref_doctype": "Task",
			"query": (
				"select count(*) as value from `tabTask` "
				"where status in ('Open', 'Working', 'Pending Review', 'Blocked')"
			),
		},
		{
			"report_name": "PM Overdue Tasks Count",
			"ref_doctype": "Task",
			"query": "select count(*) as value from `tabTask` where status = 'Overdue'",
		},
		{
			"report_name": "PM Pending Extra Hours Count",
			"ref_doctype": "Additional Hours Request",
			"query": (
				"select count(*) as value from `tabAdditional Hours Request` "
				"where status = 'Pending'"
			),
		},
		{
			"report_name": "PM Extra Hours Approved Sum",
			"ref_doctype": "Additional Hours Request",
			"query": (
				"select coalesce(sum(additional_hours_requested), 0) as value "
				"from `tabAdditional Hours Request` where status = 'Approved'"
			),
		},
		{
			"report_name": "PM Hours This Week Sum",
			"ref_doctype": "Timesheet",
			"query": (
				"select coalesce(sum(total_hours), 0) as value from `tabTimesheet` "
				"where docstatus = 1 and yearweek(start_date, 1) = yearweek(curdate(), 1)"
			),
		},
		{
			"report_name": "PM Open Issues Count",
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
			"label": "PM Open Tasks",
			"type": "Report",
			"report_name": "PM Open Tasks Count",
			"report_field": "value",
			"report_function": "Sum",
		},
		{
			"label": "PM Overdue Tasks",
			"type": "Report",
			"report_name": "PM Overdue Tasks Count",
			"report_field": "value",
			"report_function": "Sum",
		},
		{
			"label": "PM Pending Extra Hours Approvals",
			"type": "Report",
			"report_name": "PM Pending Extra Hours Count",
			"report_field": "value",
			"report_function": "Sum",
		},
		{
			"label": "PM Extra Hours Approved",
			"type": "Report",
			"report_name": "PM Extra Hours Approved Sum",
			"report_field": "value",
			"report_function": "Sum",
		},
		{
			"label": "PM Hours Logged This Week",
			"type": "Report",
			"report_name": "PM Hours This Week Sum",
			"report_field": "value",
			"report_function": "Sum",
		},
		{
			"label": "PM Open Issues",
			"type": "Report",
			"report_name": "PM Open Issues Count",
			"report_field": "value",
			"report_function": "Sum",
		},
		# "My work" — Document Type, visible to everyone, scoped to the viewer
		{
			"label": "PM My Open Tasks",
			"type": "Document Type",
			"document_type": "Task",
			"function": "Count",
			"filters": [["Task", "status", "not in", ["Completed", "Cancelled"]]],
			"dynamic_filters": me_assign_filter("Task"),
		},
		{
			"label": "PM My Overdue Tasks",
			"type": "Document Type",
			"document_type": "Task",
			"function": "Count",
			"filters": [["Task", "status", "=", "Overdue"]],
			"dynamic_filters": me_assign_filter("Task"),
		},
		{
			"label": "PM My Hours This Week",
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
			"label": "PM My Pending Extra Hours Requests",
			"type": "Document Type",
			"document_type": "Additional Hours Request",
			"function": "Count",
			"filters": [["Additional Hours Request", "status", "=", "Pending"]],
			"dynamic_filters": [["Additional Hours Request", "requested_by", "=", "frappe.session.user"]],
		},
		{
			"label": "PM My Approved Extra Hours",
			"type": "Document Type",
			"document_type": "Additional Hours Request",
			"function": "Sum",
			"aggregate_function_based_on": "additional_hours_requested",
			"filters": [["Additional Hours Request", "status", "=", "Approved"]],
			"dynamic_filters": [["Additional Hours Request", "requested_by", "=", "frappe.session.user"]],
		},
		{
			"label": "PM My Open Issues",
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
			"chart_name": "PM Tasks by Status",
			"chart_type": "Group By",
			"document_type": "Task",
			"group_by_based_on": "status",
			"group_by_type": "Count",
			"type": "Donut",
			"roles": ORG_ROLES,
			"filters": [],
		},
		{
			"chart_name": "PM Tasks by Work Item Type",
			"chart_type": "Group By",
			"document_type": "Task",
			"group_by_based_on": "custom_work_item_type",
			"group_by_type": "Count",
			"type": "Bar",
			"roles": ORG_ROLES,
			"filters": [],
		},
		{
			"chart_name": "PM Issues by Status",
			"chart_type": "Group By",
			"document_type": "Issue",
			"group_by_based_on": "status",
			"group_by_type": "Count",
			"type": "Donut",
			"roles": ORG_ROLES,
			"filters": [],
		},
		{
			"chart_name": "PM Workload Distribution",
			"chart_type": "Group By",
			"document_type": "ToDo",
			"group_by_based_on": "allocated_to",
			"group_by_type": "Count",
			"type": "Bar",
			"roles": ORG_ROLES,
			"filters": [["ToDo", "reference_type", "=", "Task"], ["ToDo", "status", "=", "Open"]],
		},
		{
			"chart_name": "PM Hours Logged Trend",
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
			"chart_name": "PM My Tasks by Status",
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
			"chart_name": "PM My Issues by Status",
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
			"chart_name": "PM My Hours Trend",
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
