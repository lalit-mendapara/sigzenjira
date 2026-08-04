import frappe
from frappe import _
from frappe.utils import getdate

from sigzenjira.custom.permissions import user_is_project_member


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_validate(filters)
	return _columns(), [], None, None, None


def _validate(filters):
	if not filters.project:
		# A report is callable straight over frappe.desk.query_report.run, where
		# the filter's reqd flag is never consulted.
		frappe.throw(_("Project is required."))

	# user_is_project_member already short-circuits for Administrator and for
	# every role in PROJECT_SCOPE_BYPASS_ROLES, so this is the whole guard.
	if not user_is_project_member(filters.project):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if filters.story:
		story_project = frappe.db.get_value("Task", filters.story, "project")
		if story_project != filters.project:
			frappe.throw(
				_("Story {0} does not belong to Project {1}.").format(filters.story, filters.project)
			)

	if filters.from_date and filters.to_date and getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date."))


def _columns():
	return [
		{
			"label": _("Work Item"),
			"fieldname": "work_item",
			"fieldtype": "Link",
			"options": "Task",
			"width": 260,
		},
		{"label": _("Subject"), "fieldname": "subject", "fieldtype": "Data", "width": 200},
		{"label": _("Type"), "fieldname": "work_item_type", "fieldtype": "Data", "width": 90},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Billable"), "fieldname": "is_billable", "fieldtype": "Check", "width": 80},
		{"label": _("Est Hours"), "fieldname": "expected_time", "fieldtype": "Float", "width": 100},
		{"label": _("Actual Hours"), "fieldname": "actual_time", "fieldtype": "Float", "width": 100},
		{"label": _("Variance"), "fieldname": "variance", "fieldtype": "Float", "width": 100},
		{"label": _("Billable Hours"), "fieldname": "billable_hours", "fieldtype": "Float", "width": 110},
		{
			"label": _("Non-Billable Hours"),
			"fieldname": "non_billable_hours",
			"fieldtype": "Float",
			"width": 130,
		},
		{"label": _("Amount"), "fieldname": "billing_amount", "fieldtype": "Currency", "width": 120},
	]
