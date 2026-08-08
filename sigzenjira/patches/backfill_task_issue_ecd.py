import frappe


def execute():
	# custom_task_issue_ecd is a fetch_from field, so it only fills on the next
	# save of each Task - Tasks already created from an Issue would read blank
	# until someone touched them. Copy the current value across once.
	frappe.db.sql("""
		update `tabTask` t
		inner join `tabIssue` i on i.name = t.issue
		set t.custom_task_issue_ecd = i.custom_issue_ecd
	""")
