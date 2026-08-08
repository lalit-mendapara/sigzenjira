import json

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def apply_property_setters():
	set_task_search_fields()
	set_task_costing_permlevel()
	set_task_status_options()
	set_issue_status_options()
	set_issue_field_order()
	set_timesheet_detail_billable_readonly()


def set_task_search_fields():
	# Core Frappe includes a doctype's `search_fields` as extra description
	# text under each match in a Link field's search dropdown (see
	# frappe/desk/search.py). This makes the parent_task picker show the
	# work item type next to every Task without adding any field.
	make_property_setter(
		"Task", None, "search_fields", "subject,custom_task_work_item_type", "Data", for_doctype=True
	)


COSTING_PERMLEVEL_FIELDS = ("total_costing_amount", "total_billing_amount")


def set_task_costing_permlevel():
	# Money a task cost / can be billed is manager information. Pushing both
	# fields to permlevel 1 hides them from every role that lacks a permlevel-1
	# read - see create_task_costing_permlevel_docperms (custom_permission.py)
	# for who that is.
	# work_board.py drops permlevel > 0 fields from its card payload for the same
	# reason - the board bypasses the form's permlevel handling.
	for fieldname in COSTING_PERMLEVEL_FIELDS:
		make_property_setter("Task", fieldname, "permlevel", 1, "Int")


TASK_STATUS_OPTIONS = "Open\nWorking\nPending Review\nOverdue\nCompleted\nCancelled\nBlocked"
ISSUE_STATUS_OPTIONS = "Open\nWIP\nIN-QA\nIN-UAT\nResolved\nOn Hold\nClosed"


def set_task_status_options():
	make_property_setter("Task", "status", "options", TASK_STATUS_OPTIONS, "Select")


def set_issue_status_options():
	make_property_setter("Issue", "status", "options", ISSUE_STATUS_OPTIONS, "Select")


def set_issue_field_order():
	# Project and Billable belong next to the Subject, not buried in Additional
	# Info - an Issue is scoped to a project the moment it is raised, and the
	# Issue-to-Story cycle needs both. custom_issue_is_billable has to be moved
	# explicitly rather than left to its insert_after: once a fieldname appears in
	# field_order, meta stops recomputing its position from insert_after
	# (frappe/model/meta.py:sort_fields).
	# Recomputed from the live meta rather than hardcoded, so an erpnext upgrade
	# that adds a field to Issue only needs apply_property_setters re-run. Reading
	# the meta (not the DocType doc, which carries no field_order once it is in the
	# DB) also means any field_order Property Setter already on the site is
	# preserved instead of clobbered.
	order = [f.fieldname for f in frappe.get_meta("Issue", cached=False).fields]
	if "subject" not in order:
		return
	moved = [f for f in ("project", "custom_issue_is_billable") if f in order]
	order = [f for f in order if f not in moved]
	order[order.index("subject") + 1 : order.index("subject") + 1] = moved
	make_property_setter("Issue", None, "field_order", json.dumps(order), "Data", for_doctype=True)


def set_timesheet_detail_billable_readonly():
	# Billable is forced from the Task (events/timesheet.py:force_is_billable_from_task),
	# so editing the cell would only ever be undone on save. read_only_depends_on
	# rather than a flat read_only so task-less activity rows keep their manual
	# checkbox - a flat lock would be a regression for non-task time logging.
	make_property_setter("Timesheet Detail", "is_billable", "read_only_depends_on", "eval:doc.task", "Code")
