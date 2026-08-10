import frappe

from sigzenjira.setup import add_project_billing_workspace_shortcut, sync_custom_fields


def execute():
	# The Page itself needs no patch - a standard Page JSON under a module folder
	# is synced from the filesystem on every migrate. What does not come along is
	# the Timesheet Detail review field the page writes, and the Project
	# Management workspace shortcut that makes the page findable.
	sync_custom_fields()
	add_project_billing_workspace_shortcut()
	frappe.clear_cache(doctype="Timesheet Detail")
