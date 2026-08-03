import frappe


def execute():
	# sigzenjira no longer ships or supports Kanban Boards - the Work Board page
	# (sigzenjira/page/work_board) replaced them. Drop every board on the site,
	# not just the two we used to create, plus the elevated Custom DocPerm rows
	# that let non-System-Manager roles create new ones.
	for name in frappe.get_all("Kanban Board", pluck="name"):
		frappe.delete_doc("Kanban Board", name, ignore_permissions=True, force=True)

	for name in frappe.get_all("Custom DocPerm", filters={"parent": "Kanban Board"}, pluck="name"):
		frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True)

	frappe.clear_cache(doctype="Kanban Board")
