import frappe


def execute():
	rows = frappe.get_all(
		"Task Split",
		filters={"generated_task": ["is", "set"]},
		fields=["name", "generated_task"],
	)

	for row in rows:
		actual_time = frappe.db.get_value("Task", row.generated_task, "actual_time")
		if actual_time is None:
			continue
		frappe.db.set_value("Task Split", row.name, "actual_hours", actual_time, update_modified=False)
