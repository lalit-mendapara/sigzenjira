import frappe

from sigzenjira.install import create_pm_kanban_boards


def execute():
	# Reverts the custom_project_name field added by an earlier patch -
	# kanban cards now show the Project link's title via a client-side
	# link-title cache instead (see public/js/task_list.js), so no extra
	# field on Task is needed.
	name = frappe.db.get_value("Custom Field", {"dt": "Task", "fieldname": "custom_project_name"})
	if name:
		frappe.delete_doc("Custom Field", name, ignore_permissions=True)

	if frappe.db.has_column("Task", "custom_project_name"):
		frappe.db.sql_ddl("ALTER TABLE `tabTask` DROP COLUMN `custom_project_name`")

	create_pm_kanban_boards()
