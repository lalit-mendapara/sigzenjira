import frappe


def execute():
	# The three fields added by add_billable_hours_rollup_fields are only ever
	# written by their events - set_row_non_billable_hours on Timesheet validate,
	# recompute_project_billable_hours on submit/cancel - so everything already
	# logged reads 0 until someone touches it again. Same arithmetic the events
	# do, applied once.
	frappe.db.sql("""
		update `tabTimesheet Detail`
		set custom_timesheet_detail_non_billable_hours = hours - billing_hours
	""")

	# docstatus = 1 only, matching recompute_project_billable_hours: draft and
	# cancelled hours are not part of a Project's totals.
	frappe.db.sql("""
		update `tabProject` p
		left join (
			select project, sum(hours) as hours, sum(billing_hours) as billing_hours
			from `tabTimesheet Detail`
			where docstatus = 1 and project is not null
			group by project
		) td on td.project = p.name
		set p.custom_project_billable_hours = ifnull(td.billing_hours, 0),
			p.custom_project_non_billable_hours = ifnull(td.hours, 0) - ifnull(td.billing_hours, 0)
	""")
