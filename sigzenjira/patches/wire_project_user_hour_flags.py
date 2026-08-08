import frappe


def execute():
	# Deletion only - fixtures insert and update, they never remove. The
	# create_custom_fields(get_custom_fields()) call that used to follow was dead
	# weight: the Custom Field fixture re-applies every field force=True on every
	# migrate, and sync_fixtures runs after patches (frappe/migrate.py).
	if frappe.db.exists("Custom Field", "Project-custom_extra_hours_approver"):
		frappe.delete_doc("Custom Field", "Project-custom_extra_hours_approver", ignore_permissions=True)

	if frappe.db.has_column("Project", "custom_extra_hours_approver"):
		frappe.db.sql_ddl("ALTER TABLE `tabProject` DROP COLUMN `custom_extra_hours_approver`")
