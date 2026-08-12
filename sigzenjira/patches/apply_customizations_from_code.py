import frappe

from sigzenjira.custom_permission import create_custom_docperms
from sigzenjira.property_setter import apply_property_setters
from sigzenjira.setup import (
	create_additional_hours_request_notifications,
	sync_custom_fields,
)


def execute():
	# The `fixtures` hook is gone. Custom Field, Property Setter, Custom DocPerm,
	# Report, Number Card, Dashboard Chart, Dashboard and Notification used to be
	# exported to sigzenjira/fixtures/*.json and re-imported force=True on every
	# migrate; the export filtered by doctype rather than by owner, so it also
	# scooped up pulse_sigzen's and erpnext's rows on Task/Project/Issue and
	# overwrote them from this app's JSON on every migrate.
	#
	# Python is the source of truth now. A handful of Property Setters and the
	# Task Director/Product Owner/Employee DocPerms had only ever existed in the
	# JSON - this pushes them, and everything else the fixtures used to carry,
	# onto sites that are already installed. Fresh installs get the same set from
	# setup.py:after_install.
	sync_custom_fields()
	apply_property_setters()
	create_custom_docperms()
	create_additional_hours_request_notifications()
	frappe.clear_cache(doctype="Task")
	frappe.clear_cache(doctype="Issue")
	frappe.clear_cache(doctype="Timesheet Detail")
