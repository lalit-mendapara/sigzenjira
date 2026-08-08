# Copyright (c) 2026, sigzenjira and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form

from sigzenjira.permission.project_user import get_project_approvers, user_has_project_flag


APPROVAL_STATUSES = ("Approved", "Rejected")


class AdditionalHoursRequest(Document):
	def validate(self):
		# The task field's query filter (additional_hours_request.js) only
		# restricts the Desk picker — re-check server-side so the same rule
		# holds for API calls that bypass the form entirely.
		work_item_type = frappe.db.get_value("Task", self.task, "custom_task_work_item_type")
		if work_item_type != "Task":
			frappe.throw(
				_("Additional Hours Request can only be raised against a Task, not a {0} ({1}).").format(
					work_item_type or _("unclassified item"), get_link_to_form("Task", self.task)
				)
			)

		self.validate_approver()
		self.set_approver_emails()

		if self.status == "Approved" and not self.approved_by:
			self.approved_by = frappe.session.user

		# The Task Hours and Story Budget fields are display-only: approver-only
		# visibility is a per-Project flag, which no field permlevel can express,
		# so the numbers are never stored (a stored value leaks through list
		# view, report and the API to whoever can read the request, and goes
		# stale the moment a Timesheet is submitted). The form asks
		# get_hour_summary for them live instead - clear whatever the client
		# echoed back so the DB keeps nothing to leak.
		self.update(BLANK_HOUR_SUMMARY)

	def validate_approver(self):
		# Approving/rejecting is a Project-level trust, not a role: the workflow
		# transitions are `allowed: Employee` (the broadest role with write here)
		# and the doctype's write permission is held by every Projects Manager,
		# so without this a Projects Manager who is on no Project at all could
		# approve any request in the org - exactly the people the "Extra Hours
		# Request Submitted" Notification never even tells about it.
		# Administrator/System Manager still pass, via user_has_project_flag.
		before = self.get_doc_before_save()
		if self.status == (before.status if before else None):
			return
		if self.status not in APPROVAL_STATUSES:
			return

		project = frappe.db.get_value("Task", self.task, "project")
		if not user_has_project_flag(project, "custom_project_user_approve_extra_hours"):
			frappe.throw(
				_(
					"Only a user with Approve Extra Hours access on this Project can approve or reject this request."
				),
				frappe.PermissionError,
			)

	def set_approver_emails(self):
		# Who to notify when this request goes Pending. A Notification's
		# recipients can only be a static role or a field ON the document
		# (get_list_of_recipients, frappe/email/doctype/notification), and
		# "whoever holds custom_project_user_approve_extra_hours on this request's Project"
		# is neither - so the list is resolved here and parked on the doc for
		# the Notification to read. Hidden/read-only/no_copy: plumbing, not data.
		project = frappe.db.get_value("Task", self.task, "project")
		self.approver_emails = ", ".join(get_project_approvers(project))

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

		# Notifying on Pending/Approved/Rejected is three Notification records
		# (setup.py:create_additional_hours_request_notifications), not code
		# here: they carry an editable subject/body and reach the same person by
		# bell AND email, which a hand-rolled Notification Log never could -
		# frappe refuses to email a log of type "Alert"
		# (is_email_notifications_enabled_for_type, notification_settings.py).


BLANK_TASK_HOUR_SUMMARY = {
	"task_allocated_hours": 0,
	"task_actual_hours": 0,
	"task_total_hours": 0,
}

BLANK_STORY_HOUR_SUMMARY = {
	"story": None,
	"story_expected_hours": 0,
	"story_allocated_hours": 0,
	"story_buffer_hours": 0,
}

BLANK_HOUR_SUMMARY = BLANK_TASK_HOUR_SUMMARY | BLANK_STORY_HOUR_SUMMARY


@frappe.whitelist()
def get_hour_summary(task):
	# Two questions the approver is weighing, in one round trip: what the
	# requested Task has already spent, and whether its Story still has
	# unallocated budget to absorb the request.
	if not task:
		return BLANK_HOUR_SUMMARY

	return get_task_hour_summary(task) | get_story_hour_summary(task)


def get_task_hour_summary(task):
	# The requested work item's own numbers - not approver-gated, since the
	# requester raising the request needs to see them too. actual_time is the
	# Timesheet rollup (events/timesheet.py maintains it on submit/cancel);
	# extra_hours is what earlier Additional Hours Requests already granted, so
	# total is the ceiling this Task is currently allowed to burn.
	allocated, actual, extra = frappe.db.get_value(
		"Task", task, ["expected_time", "actual_time", "custom_task_extra_hours"]
	) or (0, 0, 0)

	return {
		"task_allocated_hours": flt(allocated),
		"task_actual_hours": flt(actual),
		"task_total_hours": flt(allocated) + flt(extra),
	}


def get_story_hour_summary(task):
	# expected_time is the Story's ceiling (a PM with Allocate Hours can pin
	# it above the table - see rollup_story_expected_time), the split rows are
	# what's already committed against it, and the difference is the headroom.
	#
	# Blanks (which hide the section on the form) rather than a throw for
	# every "not for you" case - the requester opens this same form, and a
	# standalone Task has no Story budget to show in the first place.
	if not task:
		return BLANK_STORY_HOUR_SUMMARY

	story, project = frappe.db.get_value("Task", task, ["parent_task", "project"])
	if not user_has_project_flag(project, "custom_project_user_approve_extra_hours"):
		return BLANK_STORY_HOUR_SUMMARY

	if not story or frappe.db.get_value("Task", story, "custom_task_work_item_type") != "Story":
		return BLANK_STORY_HOUR_SUMMARY

	expected_hours = flt(frappe.db.get_value("Task", story, "expected_time"))
	# Approved extra hours are as committed as the original estimate - they
	# count against the Story's budget the moment they're granted, so the
	# buffer an approver reads is what's left AFTER every earlier approval.
	# The request on screen is not in here yet: extra_hours only moves on the
	# transition into Approved (see on_update).
	allocated_hours = flt(
		frappe.db.sql(
			"select sum(expected_hours) + sum(extra_hours) from `tabTask Split` where parent = %s",
			story,
		)[0][0]
	)

	return {
		"story": story,
		"story_expected_hours": expected_hours,
		"story_allocated_hours": allocated_hours,
		"story_buffer_hours": expected_hours - allocated_hours,
	}


def rollup_extra_hours(task_name, additional_hours):
	task = frappe.get_doc("Task", task_name)
	new_extra_hours = flt(task.custom_task_extra_hours) + additional_hours
	task.db_set("custom_task_extra_hours", new_extra_hours, update_modified=False)
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
		frappe.db.sql("select sum(custom_task_extra_hours) from `tabTask` where parent_task = %s", task_name)[0][0]
	)
	frappe.db.set_value("Task", task_name, "custom_task_extra_hours", children_total, update_modified=False)
	_rollup_ancestor_extra_hours(frappe.db.get_value("Task", task_name, "parent_task"))


def get_permission_query_conditions(user=None):
	# Projects Manager is deliberately NOT a bypass here: a request belongs to
	# the Project it was raised on, so membership (custom_project_user_approve_extra_hours)
	# is the gate, not the role. A Projects Manager on no Project sees only
	# their own requests, the same as anyone else.
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	return f"""(
		`tabAdditional Hours Request`.requested_by = {frappe.db.escape(user)}
		or `tabAdditional Hours Request`.task in (
			select task.name from `tabTask` task
			inner join `tabProject User` pu on pu.parent = task.project
				and pu.parenttype = 'Project' and pu.parentfield = 'users'
			where pu.user = {frappe.db.escape(user)} and pu.custom_project_user_approve_extra_hours = 1
		)
	)"""


def has_permission(doc, ptype=None, user=None, **kwargs):
	# The kwarg MUST be named `ptype`: frappe.call() matches hook arguments
	# against the signature and drops anything that doesn't match (see
	# has_controller_permissions in frappe/permissions.py), so the old
	# `permission_type` parameter never received a value and the create
	# branch below was dead code.
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	# A new, unsaved doc has no owner yet to check against — row-level
	# scoping only makes sense once requested_by is actually set, so defer
	# entirely to the role-level create permission here.
	if ptype == "create":
		return True
	if doc.requested_by == user:
		return True
	project = frappe.db.get_value("Task", doc.task, "project")
	return user_has_project_flag(project, "custom_project_user_approve_extra_hours")
