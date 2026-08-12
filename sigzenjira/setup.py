import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from sigzenjira.custom_field import CUSTOM_FIELDS
from sigzenjira.custom_permission import create_custom_docperms
from sigzenjira.property_setter import apply_property_setters


def sync_custom_fields():
	# Every Custom Field this app owns, (re-)created from the single declarative
	# source. Split out of after_install so a patch (or `bench --site <site>
	# execute sigzenjira.setup.sync_custom_fields`) can push a later addition to
	# an existing site.
	create_custom_fields(CUSTOM_FIELDS, update=True)


def after_install():
	sync_custom_fields()
	apply_property_setters()
	create_custom_docperms()
	create_additional_hours_request_workflow()
	create_additional_hours_request_notifications()
	create_ecd_notifications()
	add_work_board_workspace_shortcut()
	add_project_billing_workspace_shortcut()
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


# The cc template calls the jinja method registered by hooks.py. Notification's
# get_emails_from_template renders cc and splits the result on commas, so a
# comma-joined string is exactly what it wants; an empty string (a Task with no
# Project, or a Project with no approvers) contributes no recipients.
ECD_MANAGER_CC = "{{ ecd_alert_manager_emails(doc.project) }}"

# Frappe's trigger_daily_alerts walks every enabled Days Before/Days After
# Notification once a day, so these records ARE the whole feature - there is no
# scheduler code in this app.
#
# get_documents_for_today sets diff_days = days_in_advance, negates it for
# "Days After", and matches documents dated nowdate() + diff_days. So for an ECD
# of the 13th: Days Before/1 fires on the 12th, Days After/0 on the 13th,
# Days After/1 on the 14th. Issue.custom_issue_ecd is a Date field with no time;
# Task.exp_end_date is a Datetime (see work_board.py:_ecd_range_conditions), but
# frappe.format(..., "Date") in the message and the day-range filter in
# get_documents_for_today both absorb that, so "24 hours before" still lands at
# midnight of the previous calendar day for both doctypes.
ECD_ALERT_DOCTYPES = [
	{
		"document_type": "Task",
		"date_changed": "exp_end_date",
		"route": "task",
		# Statuses come from property_setter.py:TASK_STATUS_OPTIONS; these are
		# its two terminal ones. A finished item never generates an overdue alert.
		"condition": 'doc.status not in ("Completed", "Cancelled")',
	},
	{
		"document_type": "Issue",
		"date_changed": "custom_issue_ecd",
		"route": "issue",
		# Statuses come from property_setter.py:ISSUE_STATUS_OPTIONS.
		"condition": 'doc.status not in ("Resolved", "Closed")',
	},
]

ECD_ALERT_STAGES = [
	{
		"stage": "Due Tomorrow",
		"event": "Days Before",
		"days_in_advance": 1,
		"headline": "is due tomorrow",
	},
	{
		"stage": "Due Today",
		"event": "Days After",
		"days_in_advance": 0,
		"headline": "is due today",
	},
	{
		"stage": "Overdue",
		"event": "Days After",
		"days_in_advance": 1,
		"headline": "is overdue",
	},
]


# frappe.db.exists below makes this a create-only, run-once-per-record guard: an
# admin who later disables or edits one of the six generated records keeps that
# change permanently, since a re-run (a fresh install, or this same function
# called again) skips any name that already exists. A future correction to
# ECD_ALERT_DOCTYPES / ECD_ALERT_STAGES therefore needs a patch that explicitly
# *updates* the existing records - re-calling this function will not pick it up.
def create_ecd_notifications():
	for document in ECD_ALERT_DOCTYPES:
		for stage in ECD_ALERT_STAGES:
			name = f"{document['document_type']} ECD {stage['stage']}"
			if frappe.db.exists("Notification", name):
				continue
			ecd = f"{{{{ frappe.format(doc.{document['date_changed']}, 'Date') }}}}"
			frappe.get_doc(
				{
					"doctype": "Notification",
					# Notification.autoname falls back to the subject, which here
					# is a Jinja template - name them explicitly so the docname
					# is stable and a patch can find them again.
					"name": name,
					"document_type": document["document_type"],
					"event": stage["event"],
					"date_changed": document["date_changed"],
					"days_in_advance": stage["days_in_advance"],
					# channel "Email" + send_system_notification, as in
					# AHR_NOTIFICATIONS: one record drives the mail and the bell,
					# so there is nothing to keep in step. It stays dormant and
					# harmless until an outgoing Email Account exists.
					"channel": "Email",
					"send_system_notification": 1,
					# Resolves recipients from open ToDo rows on the document -
					# the same people the Assign To field shows.
					"send_to_all_assignees": 1,
					"enabled": 1,
					"is_standard": 0,
					"message_type": "HTML",
					"subject": f"ECD {stage['stage'].lower()}: {{{{ doc.name }}}} - {{{{ doc.subject }}}}",
					"condition": document["condition"],
					# Left explicit rather than relying on the doctype default: if that
					# default ever moves off "Python", before_save's
					# remove_invalid_condition() silently nulls `condition` above, and
					# every Completed/Cancelled/Resolved/Closed item starts getting
					# overdue mail again.
					"condition_type": "Python",
					"message": (
						f"<p>{document['document_type']} <b>{{{{ doc.name }}}}</b> - "
						f"{{{{ doc.subject }}}} {stage['headline']}.</p>"
						f"<p>ECD: {ecd}<br>Status: {{{{ doc.status }}}}</p>"
						f'<p><a href="/app/{document["route"]}/{{{{ doc.name }}}}">{{{{ doc.name }}}}</a></p>'
					),
					# Managers ride along as CC, and DO get the Desk bell too:
					# create_system_notification's recipients list is recipients + cc +
					# bcc (notification.py), so CC is included in the Notification Log,
					# not just the mail.
					"recipients": [{"cc": ECD_MANAGER_CC}],
				}
			).insert(ignore_permissions=True)


def get_work_board_workspace_shortcut():
	return {
		"label": "Work Board",
		"type": "Page",
		"link_to": "work-board",
	}


def get_project_billing_workspace_shortcut():
	return {
		"label": "Project Billing",
		"type": "Page",
		"link_to": "project-billing",
	}


def add_workspace_shortcut(shortcut, block_id):
	# The "Project Management" workspace carries a pre-existing broken shortcut
	# (Task Hour Budget Overrun -> a Report that does not exist on this site),
	# so ws.save() would blow up with LinkValidationError: the child row and the
	# `content` block are written directly, never through ws.save().
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
				"id": block_id,
				"type": "shortcut",
				"data": {"shortcut_name": shortcut["label"], "col": 4},
			}
		)
		frappe.db.set_value("Workspace", "Project Management", "content", json.dumps(content))


def add_work_board_workspace_shortcut():
	add_workspace_shortcut(get_work_board_workspace_shortcut(), "sigzenjiraWorkBoardShortcut")


def add_project_billing_workspace_shortcut():
	add_workspace_shortcut(get_project_billing_workspace_shortcut(), "sigzenjiraProjectBillingShortcut")
