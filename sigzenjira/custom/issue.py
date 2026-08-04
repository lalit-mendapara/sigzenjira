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
			"custom_work_item_type": "Story",
			"issue": issue.name,
			"project": issue.project,
			"custom_is_billable": issue.custom_is_billable,
			"priority": ISSUE_PRIORITY_TO_TASK_PRIORITY.get(issue.priority, "Medium"),
		}
	)
	task.flags.via_issue_mapping = True
	task.insert()

	return task.name
