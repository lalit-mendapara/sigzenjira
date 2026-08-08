import json

import frappe
from frappe import _

from sigzenjira.permission.project_user import user_has_project_flag


def validate_task_assign_permission(doc, method):
	# Same custom_project_user_assign_users gate as validate_task_split_assign_permission /
	# set_split_row_assignees (events/task.py) - without this, a user without
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
	if not user_has_project_flag(project, "custom_project_user_assign_users"):
		frappe.throw(_("You dont have permission to assign users on Tasks for this Project."))


def sync_todo_assignment_to_split_row(doc, method):
	# Assignment changes go through ToDo (assign_to.add/remove/close), which
	# never saves the Task itself - Task's own on_update hooks (events/task.py)
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


# Doctype -> the custom "Assign To" field that mirrors its all-time assignees.
ALL_TIME_ASSIGNEE_FIELDS = {
	"Task": "custom_task_assign_to",
	"Issue": "custom_issue_assign_to",
}


def sync_all_time_assignees(doc, method=None):
	# Appends whoever is currently in core's _assign, and never removes anyone.
	# Deliberately NOT a copy of _assign: core drops a user from _assign the
	# moment their ToDo goes Closed or Cancelled, so _assign answers "who is on
	# this now", never "who was ever on this".
	#
	# Append-only, never a rebuild: a Projects Manager prunes a stale name out of
	# the field by hand, and a rebuild would put it straight back on the next
	# ToDo save. Appending from _assign rather than from every ToDo row is what
	# makes the pruning stick - a closed assignment is gone from _assign, so it
	# is never a candidate to re-add. Only a fresh assignment brings a name back.
	fieldname = ALL_TIME_ASSIGNEE_FIELDS.get(doc.reference_type)
	if not fieldname or not doc.reference_name:
		return

	current = frappe.db.get_value(doc.reference_type, doc.reference_name, fieldname) or ""
	names = [name.strip() for name in current.split(",") if name.strip()]

	# Core's ToDo.on_update/on_trash has already rewritten _assign by the time
	# this runs (update_in_reference in frappe's todo.py), so it is current.
	raw_assign = frappe.db.get_value(doc.reference_type, doc.reference_name, "_assign")
	appended = list(names)
	for user in json.loads(raw_assign) if raw_assign else []:
		full_name = frappe.utils.get_fullname(user)
		if full_name not in appended:
			appended.append(full_name)

	if appended == names:
		return

	frappe.db.set_value(
		doc.reference_type,
		doc.reference_name,
		fieldname,
		", ".join(appended),
		update_modified=False,
	)
