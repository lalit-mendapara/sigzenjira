def get_custom_fields():
	return {
		"Project": [
			{
				"fieldname": "custom_extra_hours_approver",
				"label": "Extra Hours Approver",
				"fieldtype": "Link",
				"options": "User",
				"insert_after": "department",
				"description": "Gets notified when an Additional Hours Request is raised on any Task under this Project.",
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
		]
	}
