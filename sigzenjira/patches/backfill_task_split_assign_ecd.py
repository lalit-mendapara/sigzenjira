import json

import frappe
from frappe.utils import get_fullname, getdate


def execute():
	rows = frappe.get_all(
		"Task Split",
		filters={"generated_task": ["is", "set"]},
		fields=["name", "generated_task"],
	)

	for row in rows:
		task = frappe.db.get_value("Task", row.generated_task, ["exp_end_date", "_assign"], as_dict=True)
		if not task:
			continue

		updates = {}
		if task.exp_end_date:
			updates["ecd"] = getdate(task.exp_end_date)

		assigned_users = json.loads(task._assign) if task._assign else []
		updates["assign"] = ", ".join(get_fullname(user) for user in assigned_users)

		frappe.db.set_value("Task Split", row.name, updates, update_modified=False)
