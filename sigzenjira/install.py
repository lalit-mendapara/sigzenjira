import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from sigzenjira.custom.custom_fields import get_custom_fields
from sigzenjira.custom.dashboard import get_query_reports, get_number_cards, get_dashboard_charts, get_dashboard, get_workspace_shortcut
from sigzenjira.custom.kanban import get_kanban_boards


def after_install():
	create_custom_fields(get_custom_fields(), update=True)
	set_task_search_fields()
	set_task_status_options()
	set_issue_status_options()
	create_task_projects_manager_docperm()
	create_task_template_director_po_docperm()
	create_task_template_employee_docperm()
	create_additional_hours_request_workflow()
	create_pm_dashboard()
	create_kanban_board_docperm()
	create_pm_kanban_boards()
	frappe.clear_cache(doctype="Task")
	frappe.clear_cache(doctype="Issue")


def set_task_search_fields():
	# Core Frappe includes a doctype's `search_fields` as extra description
	# text under each match in a Link field's search dropdown (see
	# frappe/desk/search.py). This makes the parent_task picker show the
	# work item type next to every Task without adding any field.
	make_property_setter("Task", None, "search_fields", "subject,custom_work_item_type", "Data", for_doctype=True)


TASK_STATUS_OPTIONS = "Open\nWorking\nPending Review\nOverdue\nTemplate\nCompleted\nCancelled\nBlocked"
ISSUE_STATUS_OPTIONS = "Open\nWIP\nIN-QA\nIN-UAT\nResolved\nOn Hold\nClosed"


def set_task_status_options():
	make_property_setter("Task", "status", "options", TASK_STATUS_OPTIONS, "Select")


def set_issue_status_options():
	make_property_setter("Issue", "status", "options", ISSUE_STATUS_OPTIONS, "Select")


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


def create_task_template_employee_docperm():
	# Employee needs to SELECT an existing Task Template on a Story (see
	# validate_employee_story_field_restriction, custom/task.py) but must
	# never create/edit/delete one - read only, no create/write/delete.
	if frappe.db.exists("Custom DocPerm", {"parent": "Task Template", "role": "Employee"}):
		return

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": "Task Template",
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": "Employee",
			"read": 1,
			"write": 0,
			"create": 0,
			"delete": 0,
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
				{"state": "Pending", "doc_status": "0", "allow_edit": "Employee"},
				{"state": "Approved", "doc_status": "0", "allow_edit": "Employee"},
				{"state": "Rejected", "doc_status": "0", "allow_edit": "Employee"},
			],
			"transitions": [
				{"state": "Draft", "action": "Submit", "next_state": "Pending", "allowed": "Employee"},
				# "Employee" here is the broadest role holding write access to this
				# doctype (see Custom DocPerm) - the real gate on who can actually
				# approve/reject is has_permission (additional_hours_request.py),
				# which only lets Projects Manager/System Manager, the requester's
				# own project approver (Project User.custom_approve_extra_hours),
				# or (for reads) the requester through.
				{"state": "Pending", "action": "Approve", "next_state": "Approved", "allowed": "Employee"},
				{"state": "Pending", "action": "Reject", "next_state": "Rejected", "allowed": "Employee"},
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


def create_pm_dashboard():
	create_pm_dashboard_reports()
	create_pm_dashboard_cards()
	create_pm_dashboard_charts()

	dashboard = get_dashboard()
	if not frappe.db.exists("Dashboard", dashboard["dashboard_name"]):
		frappe.get_doc({"doctype": "Dashboard", **dashboard}).insert(ignore_permissions=True)

	add_pm_dashboard_workspace_shortcut()


def add_pm_dashboard_workspace_shortcut():
	# Inserting the child row directly via frappe.new_doc() (not via ws.append() +
	# ws.save()) because the existing "Project Management" workspace already has a
	# broken shortcut (Task Hour Budget Overrun → a Report that does not exist on
	# this site), which causes ws.save() to fail with LinkValidationError. This
	# approach also ensures that function is idempotent and never disturbs the
	# pre-existing workspace state.
	shortcut = get_workspace_shortcut()
	# Check if shortcut already exists
	if not frappe.db.exists("Workspace Shortcut", {"parent": "Project Management", "link_to": shortcut["link_to"]}):
		# Insert shortcut row as a child document
		doc = frappe.new_doc("Workspace Shortcut")
		doc.update({
			"parent": "Project Management",
			"parenttype": "Workspace",
			"parentfield": "shortcuts",
			**shortcut,
		})
		doc.insert(ignore_permissions=True)

	# The shortcuts child table alone doesn't render anything — Frappe's workspace
	# UI builds the page layout from the `content` field (EditorJS-style JSON
	# blocks) and only shows a "shortcut" block if `content` has one whose
	# `shortcut_name` matches a row in `shortcuts` by label (see
	# frappe/public/js/frappe/views/workspace/blocks/block.js make()). Written via
	# frappe.db.set_value for the same reason as above: ws.save() would crash on
	# the pre-existing broken "Task Hour Budget Overrun" shortcut link.
	content = json.loads(frappe.db.get_value("Workspace", "Project Management", "content") or "[]")
	already_has_block = any(
		block.get("type") == "shortcut" and block.get("data", {}).get("shortcut_name") == shortcut["label"]
		for block in content
	)
	if not already_has_block:
		content.append(
			{
				"id": "sigzenjiraPmDashboardShortcut",
				"type": "shortcut",
				"data": {"shortcut_name": shortcut["label"], "col": 4},
			}
		)
		frappe.db.set_value("Workspace", "Project Management", "content", json.dumps(content))


def create_kanban_board_docperm():
	# Core Kanban Board only grants read to Desk User / System Manager, and no
	# sigzenjira role holds Desk User — so without this, nobody but System
	# Manager can open any Kanban board. Same Custom DocPerm gotcha as
	# create_task_projects_manager_docperm: mirror existing rows first.
	for perm in frappe.get_all("DocPerm", filters={"parent": "Kanban Board"}, fields=["role", *PERM_FLAG_FIELDS]):
		if frappe.db.exists("Custom DocPerm", {"parent": "Kanban Board", "role": perm.role, "permlevel": perm.permlevel}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Kanban Board",
				"parenttype": "DocType",
				"parentfield": "permissions",
				**perm,
			}
		).insert(ignore_permissions=True)

	for role in ("Employee", "Projects User"):
		if frappe.db.exists("Custom DocPerm", {"parent": "Kanban Board", "role": role}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Kanban Board",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"read": 1,
			}
		).insert(ignore_permissions=True)

	for role in ("Director", "Product Owner", "Projects Manager"):
		if frappe.db.exists("Custom DocPerm", {"parent": "Kanban Board", "role": role}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Kanban Board",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"read": 1,
				"write": 1,
				"create": 1,
				"delete": 0,
				"report": 1,
				"export": 1,
			}
		).insert(ignore_permissions=True)


def create_pm_kanban_boards():
	# `fields`/`show_labels` control which extra fields render on each card
	# (frappe.desk.doctype.kanban_board.kanban_board.save_settings does the
	# same doc.fields = json.dumps(...) assignment despite both being
	# read_only in the DocType - that flag only blocks user-driven form
	# edits, not programmatic writes). Re-applied on every call (not just at
	# creation) so a later change to get_kanban_boards()'s field list reaches
	# boards that already exist on this site via the patch re-running.
	for board in get_kanban_boards():
		name = board["kanban_board_name"]
		card_settings = {
			"filters": frappe.as_json(board["filters"]),
			"fields": frappe.as_json(board["fields"]),
			"show_labels": board["show_labels"],
		}
		if frappe.db.exists("Kanban Board", name):
			frappe.db.set_value("Kanban Board", name, card_settings)
			continue
		doc_dict = {
			"doctype": "Kanban Board",
			"kanban_board_name": name,
			"reference_doctype": board["reference_doctype"],
			"field_name": board["field_name"],
			"private": board["private"],
			"columns": [{"column_name": column} for column in board["columns"]],
			**card_settings,
		}
		frappe.get_doc(doc_dict).insert(ignore_permissions=True)
