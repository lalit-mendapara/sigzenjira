import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from sigzenjira.custom.custom_fields import get_custom_fields
from sigzenjira.custom.dashboard import get_query_reports, get_number_cards, get_dashboard_charts


def after_install():
	create_custom_fields(get_custom_fields(), update=True)
	set_task_search_fields()
	create_task_projects_manager_docperm()
	create_task_template_director_po_docperm()
	create_additional_hours_request_workflow()
	frappe.clear_cache(doctype="Task")


def set_task_search_fields():
	# Core Frappe includes a doctype's `search_fields` as extra description
	# text under each match in a Link field's search dropdown (see
	# frappe/desk/search.py). This makes the parent_task picker show the
	# work item type next to every Task without adding any field.
	make_property_setter("Task", None, "search_fields", "subject,custom_work_item_type", "Data", for_doctype=True)


PERM_FLAG_FIELDS = [
	"permlevel",
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"print",
	"email",
	"report",
	"import",
	"export",
	"share",
	"if_owner",
]


def create_task_projects_manager_docperm():
	# Core Task ships permission rows for Projects User, HR User, HR Manager
	# only — Projects Manager (the Additional Hours Request approver role)
	# has none, so without this they can't even open the Task linked to a
	# request they're approving/rejecting.
	# The instant a Custom DocPerm exists for a doctype, Frappe ignores ALL
	# of its standard DocPerm rows (frappe/model/meta.py get_permissions) —
	# so just adding Projects Manager here would silently strip Task access
	# from every role core already grants it to (Projects User, HR User, HR
	# Manager). Mirror those into Custom DocPerm first so nothing regresses.
	for perm in frappe.get_all("DocPerm", filters={"parent": "Task"}, fields=["role", *PERM_FLAG_FIELDS]):
		if frappe.db.exists("Custom DocPerm", {"parent": "Task", "role": perm.role, "permlevel": perm.permlevel}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Task",
				"parenttype": "DocType",
				"parentfield": "permissions",
				**perm,
			}
		).insert(ignore_permissions=True)

	if frappe.db.exists("Custom DocPerm", {"parent": "Task", "role": "Projects Manager"}):
		return

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": "Task",
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": "Projects Manager",
			"read": 1,
			"write": 1,
			"create": 1,
			"delete": 0,
			"report": 1,
			"export": 1,
		}
	).insert(ignore_permissions=True)


def create_task_template_director_po_docperm():
	# Task Template ships permission rows for Projects Manager, System
	# Manager, Projects User only — Director and Product Owner (both allowed
	# to set any Work Item Type, including Story) have none, so without this
	# they can't create a Task Template or even select one in a Story's
	# Task Template picker. Same Custom DocPerm gotcha as
	# create_task_projects_manager_docperm above: mirror existing rows first.
	for perm in frappe.get_all("DocPerm", filters={"parent": "Task Template"}, fields=["role", *PERM_FLAG_FIELDS]):
		if frappe.db.exists("Custom DocPerm", {"parent": "Task Template", "role": perm.role, "permlevel": perm.permlevel}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Task Template",
				"parenttype": "DocType",
				"parentfield": "permissions",
				**perm,
			}
		).insert(ignore_permissions=True)

	for role in ("Director", "Product Owner"):
		if frappe.db.exists("Custom DocPerm", {"parent": "Task Template", "role": role}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Task Template",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"read": 1,
				"write": 1,
				"create": 1,
				"delete": 1,
				"report": 1,
				"export": 1,
				"share": 1,
				"email": 1,
				"print": 1,
			}
		).insert(ignore_permissions=True)


def create_additional_hours_request_workflow():
	# Workflow States/Actions are Link fields to their own master doctypes
	# (Workflow State / Workflow Action Master), not free text — "Pending",
	# "Approved", "Rejected", "Approve", "Reject" already ship as core
	# defaults; "Draft" and "Submit" don't, so those need creating first.
	if not frappe.db.exists("Workflow State", "Draft"):
		frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": "Draft"}).insert(
			ignore_permissions=True
		)
	if not frappe.db.exists("Workflow Action Master", "Submit"):
		frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": "Submit"}).insert(
			ignore_permissions=True
		)

	if frappe.db.exists("Workflow", "Additional Hours Request Workflow"):
		return

	frappe.get_doc(
		{
			"doctype": "Workflow",
			"workflow_name": "Additional Hours Request Workflow",
			"document_type": "Additional Hours Request",
			"workflow_state_field": "status",
			"is_active": 1,
			"send_email_alert": 0,
			"states": [
				{"state": "Draft", "doc_status": "0", "allow_edit": "Employee"},
				{"state": "Pending", "doc_status": "0", "allow_edit": "Projects Manager"},
				{"state": "Approved", "doc_status": "0", "allow_edit": "Projects Manager"},
				{"state": "Rejected", "doc_status": "0", "allow_edit": "Projects Manager"},
			],
			"transitions": [
				{"state": "Draft", "action": "Submit", "next_state": "Pending", "allowed": "Employee"},
				{"state": "Pending", "action": "Approve", "next_state": "Approved", "allowed": "Projects Manager"},
				{"state": "Pending", "action": "Reject", "next_state": "Rejected", "allowed": "Projects Manager"},
			],
		}
	).insert(ignore_permissions=True)


def create_pm_dashboard_reports():
	for report in get_query_reports():
		if frappe.db.exists("Report", report["report_name"]):
			continue
		frappe.get_doc(
			{
				"doctype": "Report",
				"report_name": report["report_name"],
				"ref_doctype": report["ref_doctype"],
				"report_type": "Query Report",
				"is_standard": "No",
				"query": report["query"],
				"roles": [{"role": "Projects Manager"}],
			}
		).insert(ignore_permissions=True)


def create_pm_dashboard_cards():
	for card in get_number_cards():
		if frappe.db.exists("Number Card", card["label"]):
			continue
		doc_dict = {"doctype": "Number Card", **card}
		if "filters" in doc_dict:
			doc_dict["filters_json"] = frappe.as_json(doc_dict.pop("filters"))
		if "dynamic_filters" in doc_dict:
			doc_dict["dynamic_filters_json"] = frappe.as_json(doc_dict.pop("dynamic_filters"))
		frappe.get_doc(doc_dict).insert(ignore_permissions=True)


def create_pm_dashboard_charts():
	for chart in get_dashboard_charts():
		if frappe.db.exists("Dashboard Chart", chart["chart_name"]):
			continue
		doc_dict = {"doctype": "Dashboard Chart", **chart}
		doc_dict["roles"] = [{"role": role} for role in doc_dict.pop("roles")]
		doc_dict["filters_json"] = frappe.as_json(doc_dict.pop("filters", []))
		if "dynamic_filters" in doc_dict:
			doc_dict["dynamic_filters_json"] = frappe.as_json(doc_dict.pop("dynamic_filters"))
		frappe.get_doc(doc_dict).insert(ignore_permissions=True)
