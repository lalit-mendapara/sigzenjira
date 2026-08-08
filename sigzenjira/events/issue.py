import frappe

ISSUE_PRIORITY_TO_TASK_PRIORITY = {"Low": "Low", "Medium": "Medium", "High": "High", "Urgent": "Urgent"}


@frappe.whitelist()
def make_story(issue_name):
	issue = frappe.get_doc("Issue", issue_name)

	task = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": issue.subject,
			"description": issue.description,
			"custom_task_work_item_type": "Story",
			"issue": issue.name,
			"project": issue.project,
			"custom_task_is_billable": issue.custom_issue_is_billable,
			"priority": ISSUE_PRIORITY_TO_TASK_PRIORITY.get(issue.priority, "Medium"),
		}
	)
	task.flags.via_issue_mapping = True
	task.insert()

	return task.name


def sync_description_to_story(doc, method):
	# The Story's description is read-only in the Desk (public/js/task.js) because
	# the Issue owns it - so every later edit on the Issue has to be pushed down,
	# or the Story keeps whatever text existed at make_story time.
	if not doc.has_value_changed("description"):
		return

	story = frappe.db.get_value("Task", {"issue": doc.name, "custom_task_work_item_type": "Story"})
	if not story:
		return

	# db.set_value, not doc.save(): the Story's validate chain (hour budget,
	# split rollup) has nothing to do with a description edit, and a Story that
	# currently fails one of those checks must not block the Issue's save.
	frappe.db.set_value("Task", story, "description", doc.description)
