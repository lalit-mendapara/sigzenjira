import frappe


def execute():
	# depends_on ("Task Depends On") is now fully system-managed - core's
	# populate_depends_on adds rows when a child Task is created, and
	# cleanup_task_references_on_delete (custom/task.py) removes them when
	# that Task is deleted. Manual edits from the grid would only fight
	# those two.
	frappe.make_property_setter(
		{
			"doctype": "Task",
			"fieldname": "depends_on",
			"property": "read_only",
			"value": "1",
			"property_type": "Check",
		}
	)
