import frappe


def execute():
	# Label only - fieldname stays custom_project_user_set_work_item_type.
	name = "Project User-custom_project_user_set_work_item_type"
	if not frappe.db.exists("Custom Field", name):
		return

	frappe.db.set_value("Custom Field", name, "label", "Can Create Epic/Story/Task")
	frappe.clear_cache(doctype="Project User")
