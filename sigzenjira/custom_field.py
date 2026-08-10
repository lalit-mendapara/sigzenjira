# Every Custom Field this app owns, in one declarative dict.
#
# Naming convention: custom_<doctype>_<name>, lowercased with spaces as
# underscores - custom_task_work_item_type, custom_project_user_allocate_hours.
# The doctype segment is what keeps a field unambiguous when the same concept
# lives on several doctypes: Billable exists on Task, Project and Issue, and
# before the rename all three shared one fieldname, which is why
# events/billable.py has to resolve it through BILLABLE_FIELDS rather than a
# single constant. Adding a field? Follow the convention, then ship a patch
# that calls create_custom_fields for it (see patches.txt) - this app has no
# `fixtures` hook, so nothing re-applies this dict on migrate by itself.


# Locks the Assign To box for everyone but a Projects Manager. Evaluated
# client-side with `new Function`, so globals like frappe.user_roles are in
# scope (frappe/public/js/frappe/utils/utils.js:eval).
ASSIGN_TO_READ_ONLY_DEPENDS_ON = 'eval:!frappe.user_roles.includes("Projects Manager")'


CUSTOM_FIELDS = {
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
			# Anchored before `priority`, not after `is_active`: pulse_sigzen
			# chains its Project fields off `priority` and ends that chain with
			# a Section Break (custom_section_break_billing_details) that is
			# never closed before core's department/is_active. Anything after
			# `priority` in insert_after order therefore lands INSIDE that
			# section, which carries depends_on "eval:doc.custom_is_billable" -
			# the whole section wrapper is hidden when pulse's own Is Billable
			# is unticked, taking this field with it.
			"insert_after": "status",
			"default": "0",
		},
		{
			# The Task-level rollup (custom_task_billable_hours) walks parent_task
			# and stops at the Epic - nothing in that chain reaches the Project.
			# See recompute_project_billable_hours (events/timesheet.py) for why
			# this is summed off Timesheet Detail rather than off Tasks.
			"fieldname": "custom_project_billable_hours",
			"label": "Total Billable Hours",
			"fieldtype": "Float",
			"insert_after": "total_billable_amount",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "custom_project_non_billable_hours",
			"label": "Total Non-Billable Hours",
			"fieldtype": "Float",
			"insert_after": "custom_project_billable_hours",
			"read_only": 1,
			"no_copy": 1,
		},
	],
	"Timesheet Detail": [
		{
			# The remainder of a split core already stores both halves of: `hours`
			# is everything worked and core's `billing_hours` the billed share.
			# allow_on_submit because core's billing_hours is allow_on_submit too:
			# a billable-hours correction after submit has to move this with it.
			#
			# Shown with the other two billing cells or not at all
			# (property_setter.py:BILLABLE_ROW_DEPENDS_ON). The figure is still
			# written on a non-billable row - where it holds every hour worked -
			# it just has no split to explain there, so the Project Billing page
			# and the rollups read it while the row form does not show it.
			"fieldname": "custom_timesheet_detail_non_billable_hours",
			"label": "Non-Billable Hours",
			"fieldtype": "Float",
			"insert_after": "billing_hours",
			"depends_on": "eval:doc.task && doc.is_billable",
			"read_only": 1,
			"no_copy": 1,
			"allow_on_submit": 1,
		},
		{
			# Review state for the Project Billing page: a reviewer ticks a row off
			# once they have checked its billable hours. Hidden on the Timesheet
			# form itself - it says something about the reviewer's progress, not
			# about the work, and every employee filling a timesheet would
			# otherwise see a checkbox that is none of their business.
			# allow_on_submit because reviewing happens after submission, which is
			# the only time the figures are final enough to review.
			"fieldname": "custom_timesheet_detail_mark_as_read",
			"label": "Mark as Read",
			"fieldtype": "Check",
			"insert_after": "custom_timesheet_detail_non_billable_hours",
			"hidden": 1,
			"no_copy": 1,
			"allow_on_submit": 1,
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
			"in_list_view": 1,
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
			"in_list_view": 1,
			"in_standard_filter": 1,
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
