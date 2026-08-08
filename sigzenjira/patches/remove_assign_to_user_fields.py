import frappe


def execute():
	# The user-ID twins of custom_<doctype>_assign_to were short-lived: the
	# readable names field holds the same people and now carries the list
	# filter, so the second column was pure duplication. Fixtures only insert
	# and update, never remove, and Custom Field.on_trash leaves the column
	# behind - so both come out here.
	for doctype, fieldname in (("Task", "custom_task_assign_to_users"), ("Issue", "custom_issue_assign_to_users")):
		name = f"{doctype}-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True)

		if frappe.db.has_column(doctype, fieldname):
			frappe.db.sql_ddl(f"ALTER TABLE `tab{doctype}` DROP COLUMN `{fieldname}`")
