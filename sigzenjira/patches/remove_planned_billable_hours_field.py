import frappe


def execute():
	# custom_planned_billable_hours (budget + approved extra hours on billable
	# work) was dropped: billable hours are the LOGGED hours core already tracks
	# through Timesheet Detail.billing_hours, not a planned figure. Fixtures only
	# insert and update, never remove, so the field and its column have to come
	# out here.
	if frappe.db.exists("Custom Field", "Task-custom_planned_billable_hours"):
		frappe.delete_doc("Custom Field", "Task-custom_planned_billable_hours", ignore_permissions=True)

	if frappe.db.has_column("Task", "custom_planned_billable_hours"):
		frappe.db.sql_ddl("ALTER TABLE `tabTask` DROP COLUMN `custom_planned_billable_hours`")
