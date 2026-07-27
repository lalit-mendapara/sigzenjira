# Copyright (c) 2026, sigzenjira and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form


class AdditionalHoursRequest(Document):
	def validate(self):
		# The task field's query filter (additional_hours_request.js) only
		# restricts the Desk picker — re-check server-side so the same rule
		# holds for API calls that bypass the form entirely.
		work_item_type = frappe.db.get_value("Task", self.task, "custom_work_item_type")
		if work_item_type != "Task":
			frappe.throw(
				_("Additional Hours Request can only be raised against a Task, not a {0} ({1}).").format(
					work_item_type or _("unclassified item"), get_link_to_form("Task", self.task)
				)
			)

		if self.status == "Approved" and not self.approved_by:
			self.approved_by = frappe.session.user

	def on_update(self):
		before = self.get_doc_before_save()

		# Roll up only on the transition INTO Approved, never on a later
		# resave while already Approved — otherwise every unrelated edit
		# would add the hours again. Rejected (and any other transition)
		# intentionally does nothing here, per spec: rejecting a request
		# must never touch extra_hours anywhere in the hierarchy.
		just_approved = self.status == "Approved" and (not before or before.status != "Approved")
		if just_approved:
			rollup_extra_hours(self.task, flt(self.additional_hours_requested))

		# Pending is the state that actually needs the approver's attention
		# (Draft is still being drafted by the requester) - notify once, on
		# the transition into it, not on every resave while still Pending.
		just_submitted = self.status == "Pending" and (not before or before.status != "Pending")
		if just_submitted:
			notify_extra_hours_approver(self)


def rollup_extra_hours(task_name, additional_hours):
	task = frappe.get_doc("Task", task_name)
	new_extra_hours = flt(task.custom_extra_hours) + additional_hours
	task.db_set("custom_extra_hours", new_extra_hours, update_modified=False)
	# Mirror onto the Task Split row this Task was generated from (if any) -
	# the split table's own extra_hours column otherwise never moves off 0.
	frappe.db.set_value("Task Split", {"generated_task": task_name}, "extra_hours", new_extra_hours)
	_rollup_ancestor_extra_hours(task.parent_task)


def _rollup_ancestor_extra_hours(task_name):
	# Additional Hours Requests only ever target Task-type work items
	# (enforced above), so Story/Epic extra_hours is always a pure sum of
	# their children — never a direct value of their own, unlike actual_time.
	if not task_name:
		return
	children_total = flt(
		frappe.db.sql("select sum(custom_extra_hours) from `tabTask` where parent_task = %s", task_name)[0][0]
	)
	frappe.db.set_value("Task", task_name, "custom_extra_hours", children_total, update_modified=False)
	_rollup_ancestor_extra_hours(frappe.db.get_value("Task", task_name, "parent_task"))


def notify_extra_hours_approver(ahr_doc):
	project = frappe.db.get_value("Task", ahr_doc.task, "project")
	if not project:
		return

	approver = frappe.db.get_value("Project", project, "custom_extra_hours_approver")
	if not approver:
		return

	enqueue_create_notification(
		approver,
		{
			"type": "Alert",
			"document_type": ahr_doc.doctype,
			"document_name": ahr_doc.name,
			"subject": _("{0} requested {1} additional hour(s) on {2}").format(
				ahr_doc.requested_by, ahr_doc.additional_hours_requested, ahr_doc.task
			),
			"from_user": ahr_doc.requested_by,
		},
	)


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	if "Projects Manager" in roles or "System Manager" in roles:
		return ""
	return f"`tabAdditional Hours Request`.requested_by = {frappe.db.escape(user)}"


def has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	if "Projects Manager" in roles or "System Manager" in roles:
		return True
	# A new, unsaved doc has no owner yet to check against — row-level
	# scoping only makes sense once requested_by is actually set, so defer
	# entirely to the role-level create permission here.
	if permission_type == "create":
		return True
	return doc.requested_by == user
