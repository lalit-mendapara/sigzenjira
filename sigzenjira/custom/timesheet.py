import frappe
from frappe import _
from frappe.utils import flt, get_link_to_form


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

	direct_hours, direct_costing, direct_billing = frappe.db.sql(
		"""
		select sum(hours), sum(base_costing_amount), sum(base_billing_amount)
		from `tabTimesheet Detail` where task = %s and docstatus = 1
		""",
		task_name,
	)[0]
	children_hours, children_costing, children_billing = frappe.db.sql(
		"""
		select sum(actual_time), sum(total_costing_amount), sum(total_billing_amount)
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
			# Positive = over budget, negative = under. No floor at zero — that's
			# the useful signal.
			"custom_actual_extra_hours": actual_time - flt(expected_time),
		},
		update_modified=False,
	)

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
