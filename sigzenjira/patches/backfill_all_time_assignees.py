import frappe

from sigzenjira.events.todo import ALL_TIME_ASSIGNEE_FIELDS


def execute():
	"""Fill custom_task_assign_to / custom_issue_assign_to for docs that already
	have ToDo rows - the sync only fires on future ToDo saves."""
	for doctype, fieldname in ALL_TIME_ASSIGNEE_FIELDS.items():
		rows = frappe.get_all(
			"ToDo",
			filters={"reference_type": doctype, "allocated_to": ("is", "set")},
			fields=["reference_name", "allocated_to"],
			order_by="creation asc",
		)

		by_doc = {}
		for row in rows:
			by_doc.setdefault(row.reference_name, []).append(row.allocated_to)

		for name, assignees in by_doc.items():
			if not frappe.db.exists(doctype, name):
				continue

			full_names = [frappe.utils.get_fullname(user) for user in dict.fromkeys(assignees)]
			frappe.db.set_value(doctype, name, fieldname, ", ".join(full_names), update_modified=False)
