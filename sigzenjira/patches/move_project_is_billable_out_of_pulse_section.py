import frappe


def execute():
	# See the comment on custom_project_is_billable in custom_field.py: at
	# insert_after "is_active" the field resolved into pulse_sigzen's
	# "Billing Hours Details" section, whose depends_on hid it (and core's
	# department/is_active/percent_complete) unless pulse's own Is Billable
	# was ticked. Re-anchor before pulse's chain starts.
	if frappe.db.exists("Custom Field", "Project-custom_project_is_billable"):
		frappe.db.set_value(
			"Custom Field", "Project-custom_project_is_billable", "insert_after", "status"
		)
		frappe.clear_cache(doctype="Project")
