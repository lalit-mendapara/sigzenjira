app_name = "sigzenjira"
app_title = "Sigzenjira"
app_publisher = "sigzenjira"
app_description = "Erpnext extended Project management app"
app_email = "lalit@gmail.com"
app_license = "mit"

fixtures = [
	{"doctype": "Custom Field", "filters": [["dt", "in", ["Task", "Project User"]]]},
	{"doctype": "Property Setter", "filters": [["doc_type", "in", ["Task", "Issue"]]]},
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
	{"doctype": "Kanban Board", "filters": [["kanban_board_name", "in", ["Task Status Board", "Issue Status Board"]]]},
	{"doctype": "Custom DocPerm", "filters": [["parent", "in", ["Task", "Task Template", "Kanban Board"]]]},
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
doctype_js = {"Task": "public/js/task.js", "Timesheet": "public/js/timesheet.js", "Issue": "public/js/issue.js"}
doctype_list_js = {"Task": "public/js/task_list.js"}
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

# before_install = "sigzenjira.install.before_install"
after_install = "sigzenjira.install.after_install"

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
}

has_permission = {
	"Additional Hours Request": "sigzenjira.sigzenjira.doctype.additional_hours_request.additional_hours_request.has_permission",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Task": {
		"autoname": "sigzenjira.custom.task.autoname",
		"before_validate": "sigzenjira.custom.task.mark_parent_as_group",
		"validate": [
			"sigzenjira.custom.task.validate_work_item_type_permission",
			"sigzenjira.custom.task.validate_hierarchy",
			"sigzenjira.custom.task.validate_one_story_per_issue",
			"sigzenjira.custom.task.validate_task_split_expected_hours_permission",
			"sigzenjira.custom.task.validate_task_split_assign_permission",
			"sigzenjira.custom.task.validate_employee_story_field_restriction",
			"sigzenjira.custom.task.rollup_story_expected_time",
			"sigzenjira.custom.task.validate_hour_budget",
			"sigzenjira.custom.task.validate_expected_time_edit_permission",
			"sigzenjira.custom.task.sync_actual_extra_hours",
		],
		"on_update": [
			"sigzenjira.custom.task.generate_tasks_from_split",
			"sigzenjira.custom.task.sync_split_row_edits_to_generated_task",
			"sigzenjira.custom.task.sync_expected_hours_to_split_row",
			"sigzenjira.custom.task.cascade_completion_to_parent",
			"sigzenjira.custom.task.sync_issue_status_on_story_completion",
			"sigzenjira.custom.timesheet.rollup_actual_time_on_reparent",
		],
		"on_trash": "sigzenjira.custom.task.cleanup_task_references_on_delete",
	},
	"ToDo": {
		"before_insert": "sigzenjira.custom.todo.validate_task_assign_permission",
		"after_insert": "sigzenjira.custom.todo.sync_todo_assignment_to_split_row",
		"on_update": "sigzenjira.custom.todo.sync_todo_assignment_to_split_row",
		"on_trash": "sigzenjira.custom.todo.sync_todo_assignment_to_split_row",
	},
	"Timesheet": {
		"validate": "sigzenjira.custom.timesheet.validate_task_type",
		"on_submit": "sigzenjira.custom.timesheet.rollup_actual_time",
		"on_cancel": "sigzenjira.custom.timesheet.rollup_actual_time",
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

# before_tests = "sigzenjira.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "sigzenjira.custom.task.CustomTaskMixin"
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
# 	"Task": "sigzenjira.task.get_dashboard_data"
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

