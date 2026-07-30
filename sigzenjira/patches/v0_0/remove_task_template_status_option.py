import frappe

from sigzenjira.install import set_task_status_options


def execute():
	set_task_status_options()

	if frappe.db.exists("Kanban Board", "Task Status Board"):
		board = frappe.get_doc("Kanban Board", "Task Status Board")
		remaining = [c for c in board.columns if c.column_name != "Template"]
		if len(remaining) != len(board.columns):
			board.columns = remaining
			board.save(ignore_permissions=True)
