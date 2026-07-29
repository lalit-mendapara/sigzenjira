import frappe


def execute():
	# create_additional_hours_request_workflow (install.py) only inserts the
	# Workflow once - broadening "allowed"/"allow_edit" from "Projects Manager"
	# to "Employee" there doesn't reach a site where it already exists.
	# has_permission (additional_hours_request.py) is the real per-record gate
	# now (Project User.custom_approve_extra_hours), so this role is
	# intentionally broad - see the comment in install.py.
	if not frappe.db.exists("Workflow", "Additional Hours Request Workflow"):
		return

	frappe.db.set_value(
		"Workflow Document State",
		{"parent": "Additional Hours Request Workflow", "state": ["in", ["Pending", "Approved", "Rejected"]]},
		"allow_edit",
		"Employee",
	)
	frappe.db.set_value(
		"Workflow Transition",
		{"parent": "Additional Hours Request Workflow", "action": ["in", ["Approve", "Reject"]]},
		"allowed",
		"Employee",
	)
	frappe.clear_cache(doctype="Additional Hours Request")
