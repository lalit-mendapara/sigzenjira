import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from sigzenjira.custom_field import get_custom_fields
from sigzenjira.custom_permission import create_custom_docperms
from sigzenjira.dashboard.pm_dashboard import create_pm_dashboard
from sigzenjira.property_setter import apply_property_setters


def sync_custom_fields():
	# Every Custom Field this app owns, (re-)created from the single declarative
	# source. Split out of after_install so a field added later can be pushed to
	# an existing site with `bench --site <site> execute
	# sigzenjira.setup.sync_custom_fields` before exporting fixtures.
	create_custom_fields(get_custom_fields(), update=True)


def after_install():
	sync_custom_fields()
	apply_property_setters()
	create_custom_docperms()
	create_additional_hours_request_workflow()
	create_additional_hours_request_notifications()
	create_pm_dashboard()
	add_work_board_workspace_shortcut()
	frappe.clear_cache(doctype="Task")
	frappe.clear_cache(doctype="Issue")
	frappe.clear_cache(doctype="Timesheet Detail")


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
				# approve/reject is AdditionalHoursRequest.validate_approver, which
				# requires Project User.custom_project_user_approve_extra_hours on the request's
				# Project (System Manager/Administrator aside). has_permission
				# narrows visibility the same way, plus the requester's own rows.
				{"state": "Pending", "action": "Approve", "next_state": "Approved", "allowed": "Employee"},
				{"state": "Pending", "action": "Reject", "next_state": "Rejected", "allowed": "Employee"},
			],
		}
	).insert(ignore_permissions=True)


AHR_LINK = '<a href="/app/additional-hours-request/{{ doc.name }}">{{ doc.name }}</a>'

# channel "Email" + send_system_notification: one record drives both the bell and
# the mail, so there is nothing to keep in step. It stays dormant and harmless
# until an outgoing Email Account exists - send_notification_by_channel wraps the
# whole send in try/except and only writes an Error Log.
AHR_NOTIFICATIONS = [
	{
		"name": "Extra Hours Request Submitted",
		"subject": "Extra hours requested on {{ doc.task }}",
		# Resolved per-Project in AdditionalHoursRequest.set_approver_emails -
		# a role here would mail every Projects Manager in the org, which is
		# exactly the over-broad behaviour validate_approver just closed.
		"receiver_by_document_field": "approver_emails",
		"value_changed": "status",
		"condition": 'doc.status == "Pending"',
		"message": (
			"<p>{{ doc.requested_by }} requested <b>{{ doc.additional_hours_requested }}</b> "
			"additional hour(s) on Task {{ doc.task }}.</p>"
			"<p><b>Reason:</b> {{ doc.reason or '-' }}</p>"
			f"<p>Review it here: {AHR_LINK}</p>"
		),
	},
	{
		"name": "Extra Hours Request Approved",
		"subject": "Your extra hours request on {{ doc.task }} was approved",
		"receiver_by_document_field": "requested_by",
		"value_changed": "status",
		"condition": 'doc.status == "Approved"',
		"message": (
			"<p><b>{{ doc.additional_hours_requested }}</b> additional hour(s) on Task "
			"{{ doc.task }} were approved by {{ doc.approved_by }}.</p>"
			f"<p>{AHR_LINK}</p>"
		),
	},
	{
		"name": "Extra Hours Request Rejected",
		"subject": "Your extra hours request on {{ doc.task }} was rejected",
		"receiver_by_document_field": "requested_by",
		"value_changed": "status",
		"condition": 'doc.status == "Rejected"',
		"message": (
			"<p>Your request for <b>{{ doc.additional_hours_requested }}</b> additional hour(s) "
			"on Task {{ doc.task }} was rejected.</p>"
			f"<p>{AHR_LINK}</p>"
		),
	},
]


def create_additional_hours_request_notifications():
	for notification in AHR_NOTIFICATIONS:
		if frappe.db.exists("Notification", notification["name"]):
			continue
		frappe.get_doc(
			{
				"doctype": "Notification",
				# Notification.autoname falls back to the subject, which here is a
				# Jinja template - name them explicitly so the docname is stable.
				"name": notification["name"],
				"document_type": "Additional Hours Request",
				"event": "Value Change",
				"channel": "Email",
				"send_system_notification": 1,
				"enabled": 1,
				"is_standard": 0,
				"message_type": "HTML",
				"subject": notification["subject"],
				"value_changed": notification["value_changed"],
				"condition": notification["condition"],
				"message": notification["message"],
				"recipients": [{"receiver_by_document_field": notification["receiver_by_document_field"]}],
			}
		).insert(ignore_permissions=True)


def get_work_board_workspace_shortcut():
	return {
		"label": "Work Board",
		"type": "Page",
		"link_to": "work-board",
	}


def add_work_board_workspace_shortcut():
	# Same LinkValidationError landmine as add_pm_dashboard_workspace_shortcut
	# (dashboard/pm_dashboard.py): the child row and the `content` block are
	# written directly, never through ws.save().
	shortcut = get_work_board_workspace_shortcut()
	if not frappe.db.exists(
		"Workspace Shortcut", {"parent": "Project Management", "link_to": shortcut["link_to"]}
	):
		doc = frappe.new_doc("Workspace Shortcut")
		doc.update(
			{
				"parent": "Project Management",
				"parenttype": "Workspace",
				"parentfield": "shortcuts",
				**shortcut,
			}
		)
		doc.insert(ignore_permissions=True)

	content = json.loads(frappe.db.get_value("Workspace", "Project Management", "content") or "[]")
	already_has_block = any(
		block.get("type") == "shortcut" and block.get("data", {}).get("shortcut_name") == shortcut["label"]
		for block in content
	)
	if not already_has_block:
		content.append(
			{
				"id": "sigzenjiraWorkBoardShortcut",
				"type": "shortcut",
				"data": {"shortcut_name": shortcut["label"], "col": 4},
			}
		)
		frappe.db.set_value("Workspace", "Project Management", "content", json.dumps(content))
