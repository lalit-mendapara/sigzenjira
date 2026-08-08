# Every Custom Field this app owns, in one declarative dict.
#
# Naming convention: custom_<doctype>_<name>, lowercased with spaces as
# underscores - custom_task_work_item_type, custom_project_user_allocate_hours.
# The doctype segment is what keeps a field unambiguous when the same concept
# lives on several doctypes: Billable exists on Task, Project and Issue, and
# before the rename all three shared one fieldname, which is why
# events/billable.py has to resolve it through BILLABLE_FIELDS rather than a
# single constant. Adding a field? Follow the convention, then run
# `bench --site <site> execute sigzenjira.setup.sync_custom_fields` and
# re-export fixtures.


# Locks the Assign To box for everyone but a Projects Manager. Evaluated
# client-side with `new Function`, so globals like frappe.user_roles are in
# scope (frappe/public/js/frappe/utils/utils.js:eval).
ASSIGN_TO_READ_ONLY_DEPENDS_ON = 'eval:!frappe.user_roles.includes("Projects Manager")'


def get_custom_fields():
	return {
		"Project User": [
			{
				"fieldname": "custom_project_user_allocate_hours",
				"label": "Allocate Hour + Billable Check/Uncheck",
				"fieldtype": "Check",
				"insert_after": "hide_timesheets",
				"description": "Can set Expected Hours on Task Split rows for this Project, and check/uncheck Billable on those rows.",
			},
			{
				"fieldname": "custom_project_user_assign_users",
				"label": "Assign Users",
				"fieldtype": "Check",
				"insert_after": "custom_project_user_allocate_hours",
				"description": "Can assign users on Task Split rows for this Project.",
			},
			{
				"fieldname": "custom_project_user_approve_extra_hours",
				"label": "Approve Extra Hours",
				"fieldtype": "Check",
				"insert_after": "custom_project_user_assign_users",
				"description": "Gets notified of, and can approve/reject, Additional Hours Requests under this Project.",
			},
			{
				"fieldname": "custom_project_user_set_work_item_type",
				"label": "Set Work Item Type",
				"fieldtype": "Check",
				"insert_after": "custom_project_user_approve_extra_hours",
				"description": "Can classify Tasks as Epic/Story/Task under this Project (everyone else is limited to Sub-task).",
			},
		],
		"Project": [
			{
				"fieldname": "custom_project_is_billable",
				"label": "Billable",
				"fieldtype": "Check",
				"insert_after": "is_active",
				"default": "0",
			},
		],
		"Issue": [
			{
				"fieldname": "custom_issue_is_billable",
				"label": "Billable",
				"fieldtype": "Check",
				"insert_after": "project",
				"default": "0",
			},
			{
				# See custom_task_assign_to.
				"fieldname": "custom_issue_assign_to",
				"label": "Assign To",
				"fieldtype": "Small Text",
				"insert_after": "issue_type",
				# See custom_task_assign_to.
				"read_only": 0,
				"read_only_depends_on": ASSIGN_TO_READ_ONLY_DEPENDS_ON,
				"no_copy": 1,
				"in_standard_filter": 1,
			},
			{
				# Expected Completion Date, same meaning as Task.exp_end_date.
				"fieldname": "custom_issue_ecd",
				"label": "ECD",
				"fieldtype": "Date",
				"insert_after": "custom_issue_assign_to",
			},
		],
		"Task": [
			{
				"fieldname": "custom_task_work_item_type",
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
				"fieldname": "custom_task_is_billable",
				"label": "Billable",
				"fieldtype": "Check",
				"insert_after": "custom_task_work_item_type",
				"default": "0",
			},
			{
				# Every user ever assigned, full names, comma separated. Core's
				# _assign only holds *open* assignments - frappe's ToDo
				# update_in_reference filters status not in (Cancelled, Closed),
				# so completing an assignment wipes the doc back to looking
				# unassigned. This field is rebuilt from the ToDo rows themselves
				# (events/todo.py:sync_all_time_assignees) so the history survives
				# completion and stays reportable/filterable.
				"fieldname": "custom_task_assign_to",
				"label": "Assign To",
				"fieldtype": "Small Text",
				"insert_after": "parent_task",
				# Editable for a Projects Manager only, so they can prune a name
				# that is no longer in core's Assigned To. Everyone else gets a
				# read-only box. The sync is append-only for exactly this reason
				# (events/todo.py) - a rebuild would undo the pruning.
				"read_only": 0,
				"read_only_depends_on": ASSIGN_TO_READ_ONLY_DEPENDS_ON,
				"no_copy": 1,
				# Text filter in the list view header - matches with `like %name%`,
				# which is what makes a comma-separated cell searchable per user.
				"in_standard_filter": 1,
				"in_list_view": 1,
			},
			{
				# Sits above the Timeline section (insert_after "duration", the
				# last field before sb_timeline) so logged billing is read before
				# the dates, not buried under Costing.
				"fieldname": "custom_task_billing_hours_section",
				"label": "Task Billing Hours Details",
				"fieldtype": "Section Break",
				"insert_after": "duration",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_task_billable_hours",
				"label": "Billable Hours",
				"fieldtype": "Float",
				"insert_after": "custom_task_billing_hours_section",
				"read_only": 1,
				"no_copy": 1,
				"depends_on": "eval:doc.custom_task_is_billable",
			},
			{
				# The rest of actual_time: hours logged against work that was not
				# billable when the Timesheet was submitted. No depends_on - a
				# non-billable Task is exactly where this needs to be visible.
				"fieldname": "custom_task_non_billable_hours",
				"label": "Non Billable Hours",
				"fieldtype": "Float",
				"insert_after": "custom_task_billable_hours",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				# Story only: set when a user with Allocate Hours types an
				# Expected Time above the Task Split total. While set,
				# expected_time stops auto-tracking that total (it only moves
				# again if the table grows past it).
				"fieldname": "custom_task_story_budget_is_manual",
				"label": "Story Budget Is Manual",
				"fieldtype": "Check",
				"insert_after": "expected_time",
				"default": "0",
				"read_only": 1,
				"hidden": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_task_extra_hours",
				"label": "Extra Hours",
				"fieldtype": "Float",
				"insert_after": "expected_time",
				"default": "0",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_task_actual_extra_hours",
				"label": "Actual Extra Hours",
				"fieldtype": "Float",
				"insert_after": "actual_time",
				"read_only": 1,
				"no_copy": 1,
			},
			{
				"fieldname": "custom_task_issue_type",
				"label": "Issue Type",
				"fieldtype": "Link",
				"options": "Issue Type",
				"insert_after": "issue",
				"fetch_from": "issue.issue_type",
				"read_only": 1,
			},
			{
				"fieldname": "custom_task_split_work_tab",
				"label": "Split Work",
				"fieldtype": "Tab Break",
				"insert_after": "template_task",
				"depends_on": 'eval:doc.custom_task_work_item_type=="Story"',
			},
			{
				# The originating Issue's ECD, at the top of the Split Work tab, so
				# the split can be planned against the date the customer was promised.
				"fieldname": "custom_task_issue_ecd",
				"label": "Issue ECD",
				"fieldtype": "Date",
				"insert_after": "custom_task_split_work_tab",
				"fetch_from": "issue.custom_issue_ecd",
				"read_only": 1,
			},
			{
				"fieldname": "custom_task_task_template",
				"label": "Task Template",
				"fieldtype": "Link",
				"options": "Task Template",
				"insert_after": "custom_task_issue_ecd",
			},
			{
				"fieldname": "custom_task_task_split",
				"label": "Task Split",
				"fieldtype": "Table",
				"options": "Task Split",
				"insert_after": "custom_task_task_template",
				"cannot_add_rows": 0,
			},
		],
	}
