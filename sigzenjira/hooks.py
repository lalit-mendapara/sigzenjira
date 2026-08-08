app_name = "sigzenjira"
app_title = "Sigzenjira"
app_publisher = "sigzenjira"
app_description = "Erpnext extended Project management app"
app_email = "lalit@gmail.com"
app_license = "mit"

fixtures = [
	{"doctype": "Custom Field", "filters": [["dt", "in", ["Task", "Project User", "Project", "Issue"]]]},
	{"doctype": "Property Setter", "filters": [["doc_type", "in", ["Task", "Issue", "Timesheet Detail"]]]},
	{
		"doctype": "Report",
		"filters": [
			[
				"report_name",
				"in",
				[
					"Open Tasks Count",
					"Overdue Tasks Count",
					"Pending Extra Hours Count",
					"Extra Hours Approved Sum",
					"Hours This Week Sum",
					"Open Issues Count",
				],
			]
		],
	},
	{
		"doctype": "Number Card",
		"filters": [
			[
				"label",
				"in",
				[
					"Open Tasks",
					"Task Overdue Count",
					"Pending Extra Hours Approvals",
					"Extra Hours Approved",
					"Hours Logged This Week",
					"Open Issues",
					"My Open Tasks",
					"My Overdue Tasks",
					"My Hours This Week",
					"My Pending Extra Hours Requests",
					"My Approved Extra Hours",
					"My Open Issues",
				],
			]
		],
	},
	{
		"doctype": "Dashboard Chart",
		"filters": [
			[
				"chart_name",
				"in",
				[
					"Tasks by Status",
					"Tasks by Work Item Type Breakdown",
					"Issues by Status",
					"Workload Distribution",
					"Hours Logged Trend",
					"My Tasks by Status",
					"My Issues by Status",
					"My Hours Trend",
				],
			]
		],
	},
	{"doctype": "Dashboard", "filters": [["dashboard_name", "=", "Project Management Dashboard"]]},
	{"doctype": "Custom DocPerm", "filters": [["parent", "in", ["Task", "Task Template"]]]},
	# Re-applied force=True on every migrate like every other fixture, so the
	# subject/message here are the source of truth - edit setup.py and
	# re-export rather than tweaking the body in Desk, which a migrate undoes.
	{
		"doctype": "Notification",
		"filters": [
			[
				"name",
				"in",
				[
					"Extra Hours Request Submitted",
					"Extra Hours Request Approved",
					"Extra Hours Request Rejected",
				],
			]
		],
	},
]

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "sigzenjira",
# 		"logo": "/assets/sigzenjira/logo.png",
# 		"title": "Sigzenjira",
# 		"route": "/sigzenjira",
# 		"has_permission": "sigzenjira.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/sigzenjira/css/sigzenjira.css"
# app_include_js = "/assets/sigzenjira/js/sigzenjira.js"

# include js, css files in header of web template
# web_include_css = "/assets/sigzenjira/css/sigzenjira.css"
# web_include_js = "/assets/sigzenjira/js/sigzenjira.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "sigzenjira/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Task": "public/js/task.js",
	"Timesheet": "public/js/timesheet.js",
	"Issue": "public/js/issue.js",
	"Project": "public/js/project.js",
}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "sigzenjira/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "sigzenjira.utils.jinja_methods",
# 	"filters": "sigzenjira.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "sigzenjira.setup.before_install"
after_install = "sigzenjira.setup.after_install"

# Uninstallation
# ------------

# before_uninstall = "sigzenjira.uninstall.before_uninstall"
# after_uninstall = "sigzenjira.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "sigzenjira.utils.before_app_install"
# after_app_install = "sigzenjira.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "sigzenjira.utils.before_app_uninstall"
# after_app_uninstall = "sigzenjira.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "sigzenjira.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "sigzenjira.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"Additional Hours Request": "sigzenjira.sigzenjira.doctype.additional_hours_request.additional_hours_request.get_permission_query_conditions",
	"Task": "sigzenjira.permission.project.task_query_conditions",
	"Project": "sigzenjira.permission.project.project_query_conditions",
}

has_permission = {
	"Additional Hours Request": "sigzenjira.sigzenjira.doctype.additional_hours_request.additional_hours_request.has_permission",
	"Task": "sigzenjira.permission.project.task_has_permission",
	"Project": "sigzenjira.permission.project.project_has_permission",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Task": {
		"autoname": "sigzenjira.events.task.autoname",
		"before_validate": "sigzenjira.events.task.mark_parent_as_group",
		"validate": [
			"sigzenjira.events.task.validate_work_item_type_permission",
			"sigzenjira.events.task.validate_hierarchy",
			"sigzenjira.events.task.validate_parent_task_is_immutable",
			"sigzenjira.events.task.validate_one_story_per_issue",
			"sigzenjira.events.task.validate_task_split_expected_hours_permission",
			"sigzenjira.events.task.validate_task_split_assign_permission",
			"sigzenjira.events.task.validate_task_split_row_deletion",
			"sigzenjira.events.task.validate_employee_story_field_restriction",
			"sigzenjira.events.task.rollup_story_expected_time",
			"sigzenjira.events.task.validate_hour_budget",
			"sigzenjira.events.task.validate_expected_time_edit_permission",
			"sigzenjira.events.task.sync_actual_extra_hours",
			"sigzenjira.events.billable.validate_billable_edit_permission",
			"sigzenjira.events.billable.validate_billable_under_billable_parent",
			"sigzenjira.events.billable.validate_task_split_billable",
			"sigzenjira.events.billable.validate_split_row_unbilling",
			"sigzenjira.events.billable.validate_no_billable_dependants",
		],
		"on_update": [
			"sigzenjira.events.task.create_split_row_for_manual_task",
			"sigzenjira.events.task.delete_tasks_for_removed_split_rows",
			"sigzenjira.events.task.generate_tasks_from_split",
			"sigzenjira.events.task.sync_split_row_edits_to_generated_task",
			"sigzenjira.events.task.sync_expected_hours_to_split_row",
			"sigzenjira.events.task.cascade_completion_to_parent",
			"sigzenjira.events.timesheet.rollup_actual_time_on_reparent",
		],
		"on_trash": "sigzenjira.events.task.cleanup_task_references_on_delete",
	},
	"Project": {
		# No validate_billable_under_billable_parent here: PARENT_SOURCES["Project"]
		# is empty (Project is the root), so it would be an unconditional no-op.
		"validate": [
			"sigzenjira.events.billable.validate_billable_edit_permission",
			"sigzenjira.events.billable.validate_no_billable_dependants",
		],
	},
	"Issue": {
		"validate": [
			"sigzenjira.events.billable.validate_billable_edit_permission",
			"sigzenjira.events.billable.validate_billable_under_billable_parent",
			"sigzenjira.events.billable.validate_no_billable_dependants",
		],
		"on_update": "sigzenjira.events.issue.sync_description_to_story",
	},
	"ToDo": {
		"before_insert": "sigzenjira.events.todo.validate_task_assign_permission",
		"after_insert": [
			"sigzenjira.events.todo.sync_todo_assignment_to_split_row",
			"sigzenjira.events.todo.sync_all_time_assignees",
		],
		"on_update": [
			"sigzenjira.events.todo.sync_todo_assignment_to_split_row",
			"sigzenjira.events.todo.sync_all_time_assignees",
		],
		# sync_all_time_assignees is append-only, so a deleted ToDo changes
		# nothing - no point firing it on_trash.
		"on_trash": "sigzenjira.events.todo.sync_todo_assignment_to_split_row",
	},
	"Timesheet": {
		"before_validate": [
			"sigzenjira.events.timesheet.force_is_billable_from_task",
			"sigzenjira.events.timesheet.resync_billing_hours",
		],
		"validate": "sigzenjira.events.timesheet.validate_task_type",
		"on_submit": "sigzenjira.events.timesheet.rollup_actual_time",
		"on_cancel": "sigzenjira.events.timesheet.rollup_actual_time",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"sigzenjira.tasks.all"
# 	],
# 	"daily": [
# 		"sigzenjira.tasks.daily"
# 	],
# 	"hourly": [
# 		"sigzenjira.tasks.hourly"
# 	],
# 	"weekly": [
# 		"sigzenjira.tasks.weekly"
# 	],
# 	"monthly": [
# 		"sigzenjira.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "sigzenjira.setup.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "sigzenjira.events.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "sigzenjira.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "sigzenjira.events.task_dashboard.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["sigzenjira.utils.before_request"]
# after_request = ["sigzenjira.utils.after_request"]

# Job Events
# ----------
# before_job = ["sigzenjira.utils.before_job"]
# after_job = ["sigzenjira.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"sigzenjira.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
