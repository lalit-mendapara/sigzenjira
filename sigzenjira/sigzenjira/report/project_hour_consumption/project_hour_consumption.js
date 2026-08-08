frappe.query_reports["Project Hour Consumption"] = {
	filters: [
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "Link",
			options: "Project",
			reqd: 1,
			on_change: function () {
				// A Story left over from the previous Project would otherwise
				// survive and be rejected server-side on every refresh.
				frappe.query_report.set_filter_value("story", "");
			},
		},
		{
			fieldname: "story",
			label: __("Story"),
			fieldtype: "Link",
			options: "Task",
			get_query: function () {
				const project = frappe.query_report.get_filter_value("project");
				const filters = { custom_task_work_item_type: "Story" };
				if (project) {
					filters.project = project;
				}
				return { filters: filters };
			},
		},
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{ fieldname: "billable_only", label: __("Billable Only"), fieldtype: "Check", default: 0 },
	],
	tree: true,
	name_field: "work_item",
	parent_field: "parent_task",
	initial_depth: 2,
};
