import frappe


def execute():
	# Reverts the custom_project_name field added by an earlier patch - it only
	# ever existed so Kanban cards could show the Project's title, and Kanban
	# Boards are gone entirely now (see remove_all_kanban_boards).
	name = frappe.db.get_value("Custom Field", {"dt": "Task", "fieldname": "custom_project_name"})
	if name:
		frappe.delete_doc("Custom Field", name, ignore_permissions=True)

	if frappe.db.has_column("Task", "custom_project_name"):
		frappe.db.sql_ddl("ALTER TABLE `tabTask` DROP COLUMN `custom_project_name`")
