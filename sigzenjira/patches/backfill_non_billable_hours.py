import frappe


def execute():
	# custom_task_non_billable_hours is only written by recompute_actual_time
	# (events/timesheet.py), which runs on Timesheet submit/cancel - so every
	# Task that already had time logged reads 0 until the next such event. It is
	# the remainder of a sum both of whose halves are already stored, so the
	# backfill is the same subtraction the rollup does.
	frappe.db.sql("""
		update `tabTask`
		set custom_task_non_billable_hours = actual_time - custom_task_billable_hours
	""")
