import frappe


def execute():
	if frappe.db.exists("Kanban Board", "Work Item Hierarchy Board"):
		frappe.delete_doc("Kanban Board", "Work Item Hierarchy Board", ignore_permissions=True)
