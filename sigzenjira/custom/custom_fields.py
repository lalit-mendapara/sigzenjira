def get_custom_fields():
	return {
		"Project User": [
			{
				"fieldname": "custom_allocate_hours",
				"label": "Allocate Hours",
				"fieldtype": "Check",
				"insert_after": "hide_timesheets",
				"description": "Can set Expected Hours on Task Split rows for this Project.",
			},
			{
				"fieldname": "custom_assign_users",
				"label": "Assign Users",
				"fieldtype": "Check",
				"insert_after": "custom_allocate_hours",
				"description": "Can assign users on Task Split rows for this Project.",
			},
			{
				"fieldname": "custom_approve_extra_hours",
				"label": "Approve Extra Hours",
				"fieldtype": "Check",
				"insert_after": "custom_assign_users",
				"description": "Gets notified of, and can approve/reject, Additional Hours Requests under this Project.",
			},
		],
		"Project": [
			{
				"fieldname": "custom_is_billable",
				"label": "Billable",
				"fieldtype": "Check",
				"insert_after": "is_active",
				"default": "0",
			},
		],
		"Issue": [
			{
				"fieldname": "custom_is_billable",
				"label": "Billable",
				"fieldtype": "Check",
				"insert_after": "project",
				"default": "0",
				"description": "Work done for this Issue can be billed. Defaults from the Project; uncheck for free support.",
			},
		],
		"Task": [
			{
				"fieldname": "custom_work_item_type",
				"label": "Work Item Type",
				"fieldtype": "Select",
				"options": "\nEpic\nStory\nTask\nSub-task",
				"insert_after": "subject",
				"reqd": 1,
				# Locked after the first save - the name (E-001-S-002-T-003) encodes
				# the type, and reparenting deliberately never renames, so a type
				# change would leave the name lying about the hierarchy.
				"set_only_once": 1,
			},
			{
				"fieldname": "custom_is_billable",
				"label": "Billable",
				"fieldtype": "Check",
				"insert_after": "custom_work_item_type",
				"default": "0",
				"description": "Time logged against this item is billable. Cannot be checked unless every parent it declares is billable.",
			},
			{
				"fieldname": "custom_extra_hours",
				"label": "Extra Hours",
				"fieldtype": "Float",
				"insert_after": "expected_time",
				"default": "0",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_actual_extra_hours",
				"label": "Actual Extra Hours",
				"fieldtype": "Float",
				"insert_after": "actual_time",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_issue_type",
				"label": "Issue Type",
				"fieldtype": "Link",
				"options": "Issue Type",
				"insert_after": "issue",
				"fetch_from": "issue.issue_type",
				"read_only": 1,
			},
			{
				"fieldname": "custom_split_work_section",
				"label": "Split Work",
				"fieldtype": "Section Break",
				"insert_after": "is_milestone",
				"depends_on": 'eval:doc.custom_work_item_type=="Story"',
			},
			{
				"fieldname": "custom_task_template",
				"label": "Task Template",
				"fieldtype": "Link",
				"options": "Task Template",
				"insert_after": "custom_split_work_section",
			},
			{
				"fieldname": "custom_task_split",
				"label": "Task Split",
				"fieldtype": "Table",
				"options": "Task Split",
				"insert_after": "custom_task_template",
				"cannot_add_rows": 0,
			},
		],
	}
