import json

import frappe
from frappe import _

from sigzenjira.custom.project_user import user_has_project_flag


def validate_task_assign_permission(doc, method):
	# Same custom_assign_users gate as validate_task_split_assign_permission /
	# set_split_row_assignees (custom/task.py) - without this, a user without
	# Assign Users access could just bypass the Task Split grid's assign
	# dialog and assign from the generated Task's own "Assigned To" sidebar.
	# Scoped to split-generated Tasks only - plain Tasks/Sub-tasks that never
	# went through a split aren't part of that budget-adjacent commitment and
	# keep normal assignment behaviour.
	if doc.reference_type != "Task":
		return

	story_name = frappe.db.get_value("Task Split", {"generated_task": doc.reference_name}, "parent")
	if not story_name:
		return

	project = frappe.db.get_value("Task", story_name, "project")
	if not user_has_project_flag(project, "custom_assign_users"):
		frappe.throw(_("You dont have permission to assign users on Tasks for this Project."))


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
