def get_kanban_boards():
	return [
		{
			"kanban_board_name": "Task Status Board",
			"reference_doctype": "Task",
			"field_name": "status",
			"columns": [
				"Open",
				"Working",
				"Pending Review",
				"Blocked",
				"Overdue",
				"Completed",
				"Cancelled",
				"Template",
			],
			"filters": [],
			"private": 0,
			"fields": ["custom_work_item_type", "project", "exp_end_date", "expected_time", "actual_time"],
			"show_labels": 1,
		},
		{
			"kanban_board_name": "Issue Status Board",
			"reference_doctype": "Issue",
			"field_name": "status",
			"columns": ["Open", "WIP", "IN-QA", "IN-UAT", "Resolved", "On Hold", "Closed"],
			"filters": [],
			"private": 0,
			"fields": ["priority", "issue_type", "opening_date"],
			"show_labels": 1,
		},
	]
