import frappe
from frappe import _
from frappe.utils import cint, flt, get_link_to_form


def force_is_billable_from_task(doc, method=None):
	# Billing is decided upstream on the work item, never per time entry.
	#
	# Must be before_validate, not validate: frappe composes doc_event handlers
	# to run AFTER the controller's own method (Document.hook in
	# frappe/model/document.py), so a validate hook would fire after core
	# Timesheet.validate() has already run calculate_hours -> update_billing_hours,
	# and the corrected flag would never reach the billing computation.
	#
	# Rows with no task (plain activity logging) keep their manual checkbox.
	task_names = {row.task for row in doc.time_logs if row.task}
	if not task_names:
		return

	billable_by_task = {
		task.name: cint(task.custom_is_billable)
		for task in frappe.get_all(
			"Task", filters={"name": ["in", list(task_names)]}, fields=["name", "custom_is_billable"]
		)
	}

	for row in doc.time_logs:
		if row.task:
			row.is_billable = billable_by_task.get(row.task, 0)


def validate_task_type(doc, method):
	# Only Task and Sub-task are real "do the work here" leaves in our
	# hierarchy. Epic/Story are pure groupings — actual_time on them is a
	# rollup only (see recompute_actual_time), never a direct log target.
	for row in doc.time_logs:
		if not row.task:
			continue
		work_item_type = frappe.db.get_value("Task", row.task, "custom_work_item_type")
		if work_item_type not in ("Task", "Sub-task"):
			frappe.throw(
				_("Row {0}: time can only be logged against a Task or Sub-task, not {1} ({2}).").format(
					row.idx, work_item_type or _("an unclassified Task"), get_link_to_form("Task", row.task)
				)
			)


def recompute_actual_time(task_name):
	if not task_name:
		return

	direct_hours, direct_costing, direct_billing, direct_billable = frappe.db.sql(
		"""
		select sum(hours), sum(base_costing_amount), sum(base_billing_amount), sum(billing_hours)
		from `tabTimesheet Detail` where task = %s and docstatus = 1
		""",
		task_name,
	)[0]
	children_hours, children_costing, children_billing, children_billable = frappe.db.sql(
		"""
		select sum(actual_time), sum(total_costing_amount), sum(total_billing_amount),
			sum(custom_billable_hours)
		from `tabTask` where parent_task = %s
		""",
		task_name,
	)[0]

	actual_time = flt(direct_hours) + flt(children_hours)
	expected_time = frappe.db.get_value("Task", task_name, "expected_time")

	frappe.db.set_value(
		"Task",
		task_name,
		{
			"actual_time": actual_time,
			# Reuses core's total_costing_amount/total_billing_amount fields (base
			# currency) — core only sums this task's own direct timesheet rows; we
			# extend both to also fold in child Sub-task/Task amounts, same rollup
			# shape as actual_time.
			"total_costing_amount": flt(direct_costing) + flt(children_costing),
			"total_billing_amount": flt(direct_billing) + flt(children_billing),
			# Core zeroes billing_hours when a Timesheet Detail row isn't
			# billable (timesheet_detail.py:update_billing_hours) — same rollup
			# shape as actual_time.
			"custom_billable_hours": flt(direct_billable) + flt(children_billable),
			# The remainder needs no rollup of its own: actual_time is every
			# logged hour and custom_billable_hours the billed share, so the
			# difference is the unbilled one at every level. It also picks up a
			# row billed for fewer hours than were worked, which core allows
			# (timesheet_detail.py:update_billing_hours only defaults
			# billing_hours to hours when it is 0).
			"custom_non_billable_hours": actual_time - (flt(direct_billable) + flt(children_billable)),
			# Overrun only — under budget reads as 0, never negative.
			"custom_actual_extra_hours": max(actual_time - flt(expected_time), 0),
		},
		update_modified=False,
	)

	# Mirrors sync_expected_hours_to_split_row (custom/task.py) but for actual
	# hours: this task_name may be a generated Task Split row's Task, and this
	# function is only ever reached via frappe.db.set_value, which doesn't
	# trigger Task's on_update doc_events - so the split row needs its own push.
	split_row = frappe.db.get_value("Task Split", {"generated_task": task_name}, "name")
	if split_row:
		frappe.db.set_value("Task Split", split_row, "actual_hours", actual_time, update_modified=False)

	parent_task = frappe.db.get_value("Task", task_name, "parent_task")
	if parent_task:
		recompute_actual_time(parent_task)


def rollup_actual_time(doc, method):
	seen = set()
	for row in doc.time_logs:
		if row.task and row.task not in seen:
			seen.add(row.task)
			recompute_actual_time(row.task)


def rollup_actual_time_on_reparent(doc, method):
	# recompute_actual_time only ever gets called from a Timesheet event, for
	# the chain above whichever Task that timesheet logged against - it never
	# fires just because a Story/Task's parent_task link itself changes (e.g.
	# attaching an existing Story to an Epic after the fact). Whenever
	# parent_task changes, push a recompute through both the old parent (which
	# just lost this doc's hours) and the new one (which just gained them).
	if doc.is_new():
		return

	previous_parent = (doc.get_doc_before_save() or {}).get("parent_task")
	if previous_parent == doc.parent_task:
		return

	if previous_parent:
		recompute_actual_time(previous_parent)
	if doc.parent_task:
		recompute_actual_time(doc.parent_task)


def _budget_task(task_name):
	# Sub-task carries no expected_time of its own (Phase 1) - the budget
	# that matters is its parent Task's.
	work_item_type, parent_task = frappe.db.get_value(
		"Task", task_name, ["custom_work_item_type", "parent_task"]
	)
	return task_name if work_item_type == "Task" else parent_task


@frappe.whitelist()
def check_over_budget(timesheet_name):
	# Not-yet-submitted rows aren't in actual_time yet (recompute_actual_time
	# only counts docstatus=1), so this timesheet's own hours are added on
	# top of the task's current actual_time to see what submitting would do.
	doc = frappe.get_doc("Timesheet", timesheet_name)

	new_hours_by_task = {}
	for row in doc.time_logs:
		budget_task = _budget_task(row.task) if row.task else None
		if not budget_task:
			continue
		new_hours_by_task[budget_task] = new_hours_by_task.get(budget_task, 0) + flt(row.hours)

	warnings = []
	for task_name, new_hours in new_hours_by_task.items():
		current_actual, expected_time, extra_hours, subject = frappe.db.get_value(
			"Task", task_name, ["actual_time", "expected_time", "custom_extra_hours", "subject"]
		)
		# An approved Additional Hours Request raises the effective budget —
		# without this, the warning would keep firing on every timesheet even
		# after the extra hours were already granted for exactly this reason.
		effective_budget = flt(expected_time) + flt(extra_hours)
		if not effective_budget:
			# expected_time 0 means no budget declared yet (e.g. a Task created
			# via the Task Split "Create Task" escape hatch before hours are
			# known - see create_task_without_hours), not a 0h budget already
			# exhausted. Same convention as validate_hour_budget's parent_budget check.
			continue
		projected = flt(current_actual) + new_hours
		if projected > effective_budget:
			warnings.append(
				{
					"task": task_name,
					"subject": subject,
					"expected_time": effective_budget,
					"projected_actual": projected,
					"remaining": effective_budget - flt(current_actual),
				}
			)
	return warnings
