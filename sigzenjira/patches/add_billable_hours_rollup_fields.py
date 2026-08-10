import frappe

from sigzenjira.setup import sync_custom_fields


def execute():
	# Adds Project.custom_project_billable_hours / custom_project_non_billable_hours
	# and Timesheet Detail.custom_timesheet_detail_non_billable_hours. Pushed
	# through sync_custom_fields rather than a local dict so there is one source
	# of truth - create_custom_fields(update=True) is a no-op for every field
	# already on the site.
	sync_custom_fields()
	frappe.clear_cache(doctype="Project")
	frappe.clear_cache(doctype="Timesheet Detail")
