import frappe


def execute():
	# custom_non_billable_hours is only written by recompute_actual_time
	# (custom/timesheet.py), which runs on Timesheet submit/cancel - so every
	# Task that already had time logged reads 0 until the next such event. It is
	# the remainder of a sum both of whose halves are already stored, so the
	# backfill is the same subtraction the rollup does.
	frappe.db.sql("""
		update `tabTask`
		set custom_non_billable_hours = actual_time - custom_billable_hours
	""")
