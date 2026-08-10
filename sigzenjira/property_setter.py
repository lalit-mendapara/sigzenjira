import json

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def apply_property_setters():
	set_task_search_fields()
	set_task_costing_permlevel()
	set_task_status_options()
	set_task_list_view_columns()
	set_task_form_layout()
	set_issue_status_options()
	set_issue_field_order()
	set_timesheet_detail_billable_readonly()
	set_timesheet_detail_billing_layout()


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


TASK_LIST_VIEW_FIELDS = ("subject", "is_group", "is_milestone", "priority", "project", "status")


def set_task_list_view_columns():
	# The Task list's columns. custom_task_work_item_type and
	# custom_task_assign_to carry their own in_list_view in custom_field.py -
	# these are the core fields, which can only be moved with a Property Setter.
	for fieldname in TASK_LIST_VIEW_FIELDS:
		make_property_setter("Task", fieldname, "in_list_view", 1, "Check")


# Dependencies are an Epic/Task concern: a Story is planned through its Task
# Split table and a Sub-task is a split row, so neither has anything to depend
# on. Hiding the tab rather than deleting it keeps core's depends_on_tasks
# intact for the two types that do use it.
DEPENDENCIES_DEPENDS_ON = 'eval:["Epic", "Task"].includes(doc.custom_task_work_item_type)'


def set_task_form_layout():
	# Layout that insert_after on the Custom Fields can't express, because these
	# are core fields being moved around: actual vs extra hours read together
	# above Costing, and the dependency section only shows for Epic/Task.
	make_property_setter("Task", "actual_time", "insert_after", "is_milestone", "Data")
	make_property_setter("Task", "sb_costing", "insert_after", "custom_task_actual_extra_hours", "Data")
	make_property_setter("Task", "sb_depends_on", "depends_on", DEPENDENCIES_DEPENDS_ON, "Code")
	make_property_setter("Task", "dependencies_tab", "depends_on", DEPENDENCIES_DEPENDS_ON, "Code")
	make_property_setter("Task", "dependencies_tab", "hidden", 0, "Check")
	# depends_on_tasks is maintained through the Dependencies grid, not typed in.
	make_property_setter("Task", "depends_on", "read_only", 1, "Check")
	# Quick Entry can't satisfy the hierarchy rules in events/task.py (work item
	# type, parent task, hour budget), so a Task always opens the full form.
	make_property_setter("Task", None, "quick_entry", 0, "Check", for_doctype=True)
	make_property_setter("Task", None, "track_changes", 1, "Check", for_doctype=True)
	make_property_setter("Task", None, "track_views", 1, "Check", for_doctype=True)


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


# The split only means anything on a row that has a Task and whose Task is
# billable. is_billable is forced from the Task on save, so on a non-billable one
# all three cells are a foregone conclusion (0 billable, everything else
# non-billable) and only add noise to time entry.
BILLABLE_ROW_DEPENDS_ON = "eval:doc.task && doc.is_billable"

# Order matters: this is the sequence they take under Completed.
BILLING_ROW_FIELDS = ("is_billable", "billing_hours", "custom_timesheet_detail_non_billable_hours")


def set_timesheet_detail_billing_layout():
	# Core ships billing_hours at permlevel 1, and Timesheet grants permlevel 1 to
	# Accounts User alone - so on this site the field simply never rendered for
	# anyone filling a timesheet, which is why the billable split looked missing
	# rather than locked. Dropped to 0: classifying an hour is part of logging it.
	make_property_setter("Timesheet Detail", "billing_hours", "permlevel", 0, "Int")

	for fieldname in BILLING_ROW_FIELDS:
		make_property_setter("Timesheet Detail", fieldname, "depends_on", BILLABLE_ROW_DEPENDS_ON, "Code")

	# The three belong directly under Completed, beside the hours they split,
	# not in a Billing section further down the row form. Same field_order
	# mechanics as set_issue_field_order - recomputed from the live meta so an
	# erpnext upgrade only needs apply_property_setters re-run, and so pulse's
	# fields on this doctype keep the positions they already have.
	order = [f.fieldname for f in frappe.get_meta("Timesheet Detail", cached=False).fields]
	if "completed" not in order:
		return

	moved = [f for f in BILLING_ROW_FIELDS if f in order]
	order = [f for f in order if f not in moved]
	at = order.index("completed") + 1
	order[at:at] = moved

	make_property_setter(
		"Timesheet Detail", None, "field_order", json.dumps(order), "Data", for_doctype=True
	)
