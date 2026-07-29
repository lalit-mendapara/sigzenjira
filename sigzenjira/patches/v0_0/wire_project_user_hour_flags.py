import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from sigzenjira.custom.custom_fields import get_custom_fields


def execute():
	if frappe.db.exists("Custom Field", "Project-custom_extra_hours_approver"):
		frappe.delete_doc("Custom Field", "Project-custom_extra_hours_approver", ignore_permissions=True)

	if frappe.db.has_column("Project", "custom_extra_hours_approver"):
		frappe.db.sql_ddl("ALTER TABLE `tabProject` DROP COLUMN `custom_extra_hours_approver`")

	create_custom_fields(get_custom_fields(), update=True)
