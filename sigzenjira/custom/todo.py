import json

import frappe


def sync_todo_assignment_to_split_row(doc, method):
	# Assignment changes go through ToDo (assign_to.add/remove/close), which
	# never saves the Task itself - Task's own on_update hooks (custom/task.py)
	# never fire for a pure assignment change. This is the only trigger that
	# reflects the Task's live _assign back into its Task Split row's Assign
	# display. By the time this runs, core ToDo.on_update/on_trash has already
	# rewritten Task._assign (see update_in_reference in frappe's todo.py), so
	# reading it here is always current.
	if doc.reference_type != "Task":
		return

	split_row = frappe.db.get_value("Task Split", {"generated_task": doc.reference_name}, "name")
	if not split_row:
		return

	raw_assign = frappe.db.get_value("Task", doc.reference_name, "_assign")
	assigned_users = json.loads(raw_assign) if raw_assign else []
	full_names = [frappe.utils.get_fullname(user) for user in assigned_users]

	frappe.db.set_value("Task Split", split_row, "assign", ", ".join(full_names), update_modified=False)
