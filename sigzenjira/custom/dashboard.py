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
