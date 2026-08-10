import frappe

from sigzenjira.property_setter import set_timesheet_detail_billing_layout
from sigzenjira.setup import sync_custom_fields


def execute():
	# Three separate things had to line up before the billable split was usable
	# on a timesheet row, and only the first was visible as a bug:
	#
	# 1. billing_hours is permlevel 1 in core erpnext and Timesheet grants
	#    permlevel 1 to Accounts User only, so the field rendered for nobody
	#    filling a timesheet - it looked absent rather than locked.
	# 2. it sat in a Billing section below Project/Task, away from the hours it
	#    splits.
	# 3. it showed on rows where the split is a foregone conclusion.
	#
	# sync_custom_fields carries the matching depends_on onto
	# custom_timesheet_detail_non_billable_hours; the rest is Property Setters.
	set_timesheet_detail_billing_layout()
	sync_custom_fields()
	frappe.clear_cache(doctype="Timesheet Detail")
