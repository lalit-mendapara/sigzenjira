import json

import frappe
from frappe import _
from frappe.utils import flt

from sigzenjira.events.task import WORK_ITEM_TYPE_PRIVILEGED_ROLES
from sigzenjira.events.timesheet import recompute_actual_time, recompute_project_billable_hours
from sigzenjira.permission.project import user_is_project_member

# Director, Product Owner, Projects Manager - and System Manager, which is how
# this app spells "administrator" everywhere else. Reading and adjusting are one
# gate, not two: the page exists to review what gets invoiced, and a project's
# billable figures are not something a Projects User has any business browsing.
#
# Reusing the events/billable.py set is the point. Deciding how many of an
# hour's minutes reach the invoice is the same money decision as deciding
# whether the work is billable at all, so the two must never drift apart.
#
# Must stay in step with the `roles` list in project_billing.json: frappe's
# Page.is_permitted is a plain role intersection with no System Manager bypass,
# so that file is a separate gate and neither one implies the other.
BILLING_ROLES = WORK_ITEM_TYPE_PRIVILEGED_ROLES

# Emission order for siblings. Follows the hierarchy's own shape; anything
# unclassified sorts last so a legacy Task with no work item type never appears
# above the structured work.
WORK_ITEM_ORDER = {"Epic": 0, "Story": 1, "Task": 2, "Sub-task": 3}

TASK_FIELDS = [
	"name",
	"subject",
	"parent_task",
	"custom_task_work_item_type",
	"custom_task_is_billable",
	"custom_task_billable_hours",
	"custom_task_non_billable_hours",
	"actual_time",
]

DETAIL_FIELDS = [
	"name",
	"parent",
	"task",
	"project",
	"activity_type",
	"from_time",
	"hours",
	"billing_hours",
	"custom_timesheet_detail_non_billable_hours",
	"custom_timesheet_detail_mark_as_read",
	"is_billable",
	"sales_invoice",
]


def _guard_billing_access():
	if not BILLING_ROLES & set(frappe.get_roles(frappe.session.user)):
		frappe.throw(
			_("Only a Director, Product Owner, or Projects Manager can review billable hours."),
			frappe.PermissionError,
		)


def _guard_project_access(project):
	# Every role in BILLING_ROLES is also in PROJECT_SCOPE_BYPASS_ROLES, so today
	# this never refuses anyone who got past _guard_billing_access. Kept anyway:
	# it is the same record-level rule the Task and Project list views run on
	# (permission/project.py), so if BILLING_ROLES is ever widened to a
	# project-scoped role, these whitelisted methods stay scoped with it instead
	# of quietly becoming the one way to read any project in the company.
	if not user_is_project_member(project):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def get_bootstrap():
	_guard_billing_access()

	# Billable projects only: on a non-billable Project every row is unbilled by
	# construction (the clamp in events/billable.py forbids anything else), so
	# there is nothing on one to review or adjust.
	#
	# get_list, NOT get_all: frappe.get_all forces ignore_permissions=True, which
	# would hand a project-scoped user the whole company's project list. get_list
	# runs project_query_conditions (permission/project.py), so this is already
	# scoped to the Projects the user is a Project User on.
	projects = frappe.get_list(
		"Project",
		filters={"custom_project_is_billable": 1},
		fields=["name", "project_name", "company"],
		order_by="project_name asc",
		limit_page_length=0,
	)

	# Served rather than hardcoded in the JS so the filter's options and the
	# tree's sort order can never drift apart.
	return {"projects": projects, "work_item_types": list(WORK_ITEM_ORDER)}


def _timesheet_rows(project, from_date=None, to_date=None, employee=None):
	filters = {"project": project, "docstatus": 1}
	if from_date:
		filters["from_time"] = [">=", from_date]
	if to_date:
		# to_time rather than from_time so a row that starts on the last day of
		# the range is not dropped for finishing after midnight.
		filters["to_time"] = ["<=", f"{to_date} 23:59:59"]

	rows = frappe.get_all(
		"Timesheet Detail",
		filters=filters,
		fields=DETAIL_FIELDS,
		order_by="from_time asc",
		limit_page_length=0,
	)

	# Who logged the time lives on the parent Timesheet, not the row, so it takes
	# one lookup keyed on the parents actually in view.
	parents = {row.parent for row in rows if row.parent}
	sheets = (
		frappe.get_all(
			"Timesheet",
			filters={"name": ["in", list(parents)]},
			fields=["name", "employee", "employee_name"],
			limit_page_length=0,
		)
		if parents
		else []
	)
	by_sheet = {sheet.name: sheet for sheet in sheets}

	for row in rows:
		sheet = by_sheet.get(row.parent)
		row.employee = sheet.employee if sheet else None
		row.employee_name = (sheet.employee_name or sheet.employee) if sheet else None

	# The dropdown is built from who actually billed hours here, NOT from
	# Employee.company: a person employed by one company can log time on another
	# company's project, and scoping this by company would hide their hours from
	# the invoice review while still counting them in the project total.
	#
	# Built before the employee filter is applied, so selecting someone does not
	# collapse the list to just them.
	employees = sorted(
		{(row.employee, row.employee_name) for row in rows if row.employee},
		key=lambda pair: pair[1] or pair[0],
	)

	if employee:
		rows = [row for row in rows if row.employee == employee]

	return rows, [{"name": name, "employee_name": label} for name, label in employees]


def _detail_row(row, depth):
	return {
		"row_type": "timesheet",
		"indent": depth,
		"name": row.name,
		"timesheet": row.parent,
		"label": row.activity_type or _("Time log"),
		"from_time": row.from_time,
		"hours": flt(row.hours),
		"billing_hours": flt(row.billing_hours),
		"non_billable_hours": flt(row.custom_timesheet_detail_non_billable_hours),
		"is_billable": row.is_billable,
		"employee": row.employee,
		"employee_name": row.employee_name,
		"mark_as_read": row.custom_timesheet_detail_mark_as_read,
		# An invoiced row is frozen: changing what was already billed to a
		# customer is an invoice correction, not a timesheet edit.
		"locked": bool(row.sales_invoice),
		"sales_invoice": row.sales_invoice,
	}


def _task_row(task, depth):
	return {
		"row_type": "task",
		"indent": depth,
		"name": task.name,
		"label": task.subject,
		"work_item_type": task.custom_task_work_item_type,
		"is_billable": task.custom_task_is_billable,
		# The stored rollup, not a sum of the rows below: on an Epic or Story
		# these are the whole subtree's hours, which the rows under that node
		# alone would understate.
		#
		# ponytail: a work item's figures are all-time and ignore the
		# date/employee filters. Only the timesheet rows and the "in view" totals
		# narrow. Recompute these from the filtered rows if the mismatch
		# confuses anyone.
		"hours": flt(task.actual_time),
		"billing_hours": flt(task.custom_task_billable_hours),
		"non_billable_hours": flt(task.custom_task_non_billable_hours),
	}


def _build_tree(tasks, rows_by_task, work_item_type=None):
	names = {task.name for task in tasks}
	children = {}
	for task in tasks:
		# A parent outside this project (or deleted) would make its whole subtree
		# unreachable from the root walk, so those tasks are promoted to roots
		# rather than silently dropped.
		parent = task.parent_task if task.parent_task in names else None
		children.setdefault(parent, []).append(task)

	for bucket in children.values():
		bucket.sort(key=lambda t: (WORK_ITEM_ORDER.get(t.custom_task_work_item_type, 99), t.name))

	if work_item_type:
		# Re-root rather than filter: every work item of the chosen type becomes a
		# top-level row and keeps its whole subtree, so picking Story gives one row
		# per Story with its Tasks, Sub-tasks and time logs still nested under it.
		# A Story whose Epic is now out of view is promoted, not dropped with it.
		roots = sorted((t for t in tasks if t.custom_task_work_item_type == work_item_type), key=lambda t: t.name)
	else:
		roots = children.get(None, [])

	# validate_hierarchy already forbids a parent_task cycle, but this walk would
	# recurse until the stack blew if one ever reached the table by another route
	# (a raw db.set_value, an import). One set is cheaper than that outage.
	seen = set()

	def build(task, depth):
		# The subtree's rows, or nothing at all when no time was logged anywhere
		# under it. An empty branch is noise on a page about hours - and with a
		# date or employee filter on, it is most of the tree.
		if task.name in seen:
			return []
		seen.add(task.name)

		details = [_detail_row(row, depth + 1) for row in rows_by_task.get(task.name, [])]

		below = []
		for child in children.get(task.name, []):
			below += build(child, depth + 1)

		if not details and not below:
			return []

		return [_task_row(task, depth), *details, *below]

	out = []
	for root in roots:
		out += build(root, 0)
	return out


@frappe.whitelist()
def get_project_billing(project, from_date=None, to_date=None, employee=None, work_item_type=None):
	_guard_billing_access()
	_guard_project_access(project)

	tasks = frappe.get_all(
		"Task", filters={"project": project}, fields=TASK_FIELDS, limit_page_length=0
	)
	details, employees = _timesheet_rows(project, from_date, to_date, employee)

	rows_by_task = {}
	unassigned = []
	for row in details:
		if row.task:
			rows_by_task.setdefault(row.task, []).append(row)
		else:
			unassigned.append(row)

	# An unrecognised type would silently empty the page, so it is dropped rather
	# than passed through to a walk that can only match nothing.
	rows = _build_tree(tasks, rows_by_task, work_item_type if work_item_type in WORK_ITEM_ORDER else None)

	# Time logged against the Project with no Task at all. No Task rollup can see
	# it, but recompute_project_billable_hours counts it, so leaving it off the
	# page would make the project total look wrong. It belongs to no work item, so
	# a work item type filter is exactly when it should not appear.
	if unassigned and not work_item_type:
		rows.append(
			{
				"row_type": "task",
				"indent": 0,
				"name": "",
				"label": _("Time logged without a Task"),
				"work_item_type": "",
				"is_billable": 0,
				"hours": sum(flt(row.hours) for row in unassigned),
				"billing_hours": sum(flt(row.billing_hours) for row in unassigned),
				"non_billable_hours": sum(
					flt(row.custom_timesheet_detail_non_billable_hours) for row in unassigned
				),
			}
		)
		rows += [_detail_row(row, 1) for row in unassigned]

	# Totalled off the timesheet rows actually emitted, not off the Project's
	# stored fields: those always cover the project's whole life, and would
	# contradict the rows on screen the moment a filter is applied. Summing the
	# emitted rows rather than the query result keeps "in view" literal - a work
	# item type filter drops the no-task bucket, and the total drops with it.
	in_view = [row for row in rows if row["row_type"] == "timesheet"]

	return {
		"rows": rows,
		"employees": employees,
		"totals": {
			"hours": sum(flt(row["hours"]) for row in in_view),
			"billing_hours": sum(flt(row["billing_hours"]) for row in in_view),
			"non_billable_hours": sum(flt(row["non_billable_hours"]) for row in in_view),
		},
		"project_totals": frappe.db.get_value(
			"Project",
			project,
			["custom_project_billable_hours", "custom_project_non_billable_hours"],
			as_dict=True,
		),
	}


def _validated_updates(updates):
	by_name = {row["name"]: flt(row["billing_hours"]) for row in updates}
	rows = frappe.get_all(
		"Timesheet Detail",
		filters={"name": ["in", list(by_name)], "docstatus": 1},
		fields=["name", "parent", "task", "project", "hours", "is_billable", "sales_invoice"],
		limit_page_length=0,
	)

	if len(rows) != len(by_name):
		frappe.throw(_("Some of those timesheet rows no longer exist. Refresh the page and try again."))

	for row in rows:
		_guard_project_access(row.project)
		new_hours = by_name[row.name]

		if row.sales_invoice:
			frappe.throw(
				_("Row on {0} is already invoiced ({1}) and cannot be changed here.").format(
					row.parent, row.sales_invoice
				)
			)
		if new_hours < 0:
			frappe.throw(_("Billable hours cannot be negative."))
		if new_hours > flt(row.hours):
			frappe.throw(
				_("Billable hours cannot exceed the {0} hours actually worked on this row.").format(
					flt(row.hours)
				)
			)
		if not row.is_billable and new_hours:
			frappe.throw(
				_("This row is not billable, so its billable hours must stay 0. Change the Task instead.")
			)

	return by_name, rows


def _apply_to_timesheet(timesheet_name, by_name):
	doc = frappe.get_doc("Timesheet", timesheet_name)
	changed = []

	for row in doc.time_logs:
		if row.name not in by_name:
			continue

		previous = flt(row.billing_hours)
		row.billing_hours = by_name[row.name]
		row.custom_timesheet_detail_non_billable_hours = flt(row.hours) - flt(row.billing_hours)
		# Core's own rate maths rather than a copy of it. update_cost only fills a
		# rate that is still 0, so a billing_rate someone set by hand survives -
		# it just recomputes the amounts off the new billing_hours.
		row.update_cost(doc.employee)

		frappe.db.set_value(
			"Timesheet Detail",
			row.name,
			{
				"billing_hours": row.billing_hours,
				"custom_timesheet_detail_non_billable_hours": row.custom_timesheet_detail_non_billable_hours,
				"billing_amount": row.billing_amount,
				"base_billing_amount": row.base_billing_amount,
			},
			update_modified=False,
		)
		changed.append(f"{row.idx}: {previous} -> {flt(row.billing_hours)}")

	# Core's Timesheet.on_update_after_submit does not call
	# calculate_total_amounts, so a billing_hours change made after submit leaves
	# the parent's own totals stale. Recomputed here off the rows just written.
	doc.calculate_total_amounts()
	doc.calculate_percentage_billed()
	frappe.db.set_value(
		"Timesheet",
		timesheet_name,
		{
			"total_billable_hours": doc.total_billable_hours,
			"total_billable_amount": doc.total_billable_amount,
			"base_total_billable_amount": doc.base_total_billable_amount,
			"total_billed_amount": doc.total_billed_amount,
			"base_total_billed_amount": doc.base_total_billed_amount,
			"total_billed_hours": doc.total_billed_hours,
			"per_billed": doc.per_billed,
		},
		update_modified=False,
	)

	# The trail. These edits land on a submitted document through db.set_value,
	# which writes no version history of its own, so without this a billed figure
	# could change with nothing anywhere recording who moved it or from what.
	if changed:
		doc.add_comment(
			"Info",
			_("Billable hours adjusted from Project Billing - row {0}").format(", ".join(changed)),
		)


@frappe.whitelist()
def update_billing_hours(updates):
	if isinstance(updates, str):
		updates = json.loads(updates)

	_guard_billing_access()

	if not updates:
		return {"updated": 0}

	by_name, rows = _validated_updates(updates)

	for timesheet_name in {row.parent for row in rows}:
		_apply_to_timesheet(timesheet_name, by_name)

	# Task rollups first: recompute_project_billable_hours reads the rows, not the
	# Tasks, so the order does not matter for correctness - but a Task left stale
	# would show a figure contradicting the Project total on the same screen.
	for task in {row.task for row in rows if row.task}:
		recompute_actual_time(task)
	for project in {row.project for row in rows if row.project}:
		recompute_project_billable_hours(project)

	return {"updated": len(by_name)}


@frappe.whitelist()
def set_mark_as_read(names, value):
	if isinstance(names, str):
		names = json.loads(names)

	_guard_billing_access()

	if not names:
		return {"updated": 0}

	rows = frappe.get_all(
		"Timesheet Detail",
		filters={"name": ["in", names]},
		fields=["name", "project"],
		limit_page_length=0,
	)
	for row in rows:
		_guard_project_access(row.project)

	for row in rows:
		frappe.db.set_value(
			"Timesheet Detail",
			row.name,
			"custom_timesheet_detail_mark_as_read",
			1 if int(value) else 0,
			update_modified=False,
		)

	return {"updated": len(rows)}
