import frappe

from sigzenjira.custom.kanban import get_kanban_boards


def execute():
	canonical_names = {board["kanban_board_name"] for board in get_kanban_boards()}
	stray_names = frappe.get_all(
		"Kanban Board",
		filters={"reference_doctype": ["in", ["Task", "Issue"]], "name": ["not in", canonical_names]},
		pluck="name",
	)
	for name in stray_names:
		frappe.delete_doc("Kanban Board", name, ignore_permissions=True)
