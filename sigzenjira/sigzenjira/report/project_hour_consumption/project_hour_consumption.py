import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from sigzenjira.custom.permissions import user_is_project_member

TASK_FIELDS = [
	"name",
	"subject",
	"parent_task",
	"custom_work_item_type",
	"status",
	"custom_is_billable",
	"expected_time",
]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_validate(filters)

	by_name, children = _fetch_tree(filters.project)
	roots = _roots(filters, by_name, children)

	ordered = []
	_emit(roots, children, 0, ordered, set())

	direct = _direct_totals([task.name for task in ordered], filters)
	totals = {}
	for root in roots:
		_rollup(root, children, direct, totals, set())

	data = [_row(task, totals, root_names={root.name for root in roots}) for task in ordered]
	return _columns(), data, None, None, None


def _validate(filters):
	if not filters.project:
		# A report is callable straight over frappe.desk.query_report.run, where
		# the filter's reqd flag is never consulted.
		frappe.throw(_("Project is required."))

	# user_is_project_member already short-circuits for Administrator and for
	# every role in PROJECT_SCOPE_BYPASS_ROLES, so this is the whole guard.
	if not user_is_project_member(filters.project):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if filters.story:
		story_project = frappe.db.get_value("Task", filters.story, "project")
		if story_project != filters.project:
			frappe.throw(
				_("Story {0} does not belong to Project {1}.").format(filters.story, filters.project)
			)

	if filters.from_date and filters.to_date and getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date."))


def _fetch_tree(project):
	# Deliberately project-scoped, unlike recompute_actual_time's parent_task
	# walk (which has no project filter): a client's hour statement must not
	# carry another project's work, even if some cross-project parent/child
	# pair exists that would make the stored Task.actual_time include it.
	tasks = frappe.get_all("Task", filters={"project": project}, fields=TASK_FIELDS, order_by="name")
	by_name = {task.name: task for task in tasks}

	children = {}
	for task in tasks:
		# A parent outside this project must not orphan its child out of the
		# report - the child becomes a root instead.
		parent = task.parent_task if task.parent_task in by_name else None
		children.setdefault(parent, []).append(task)

	return by_name, children


def _roots(filters, by_name, children):
	if filters.story:
		story = by_name.get(filters.story)
		# _validate already proved the Story is in this project.
		return [story] if story else []
	return children.get(None, [])


def _emit(nodes, children, indent, ordered, visited):
	for node in nodes:
		if node.name in visited:
			# parent_task cycles are meant to be impossible; the report must
			# not be the thing that discovers one by spinning.
			continue
		visited.add(node.name)
		node.indent = indent
		ordered.append(node)
		_emit(children.get(node.name, []), children, indent + 1, ordered, visited)


def _direct_totals(task_names, filters):
	if not task_names:
		return {}

	conditions = ["docstatus = 1", "task in %(tasks)s"]
	values = {"tasks": tuple(task_names)}

	rows = frappe.db.sql(
		"""
		select task, sum(hours), sum(billing_hours), sum(base_billing_amount)
		from `tabTimesheet Detail`
		where {}
		group by task
		""".format(" and ".join(conditions)),
		values,
	)
	# billing_hours is zeroed by core when a row is not billable
	# (timesheet_detail.py:update_billing_hours), which is exactly the split
	# recompute_actual_time relies on.
	return {row[0]: (flt(row[1]), flt(row[2]), flt(row[3])) for row in rows}


def _rollup(node, children, direct, totals, visited):
	if node.name in visited:
		return (0.0, 0.0, 0.0)
	visited.add(node.name)

	hours, billable, amount = direct.get(node.name, (0.0, 0.0, 0.0))
	for child in children.get(node.name, []):
		child_hours, child_billable, child_amount = _rollup(child, children, direct, totals, visited)
		hours += child_hours
		billable += child_billable
		amount += child_amount

	totals[node.name] = (hours, billable, amount)
	return totals[node.name]


def _row(task, totals, root_names):
	hours, billable, amount = totals.get(task.name, (0.0, 0.0, 0.0))
	return {
		"work_item": task.name,
		"subject": task.subject,
		"work_item_type": task.custom_work_item_type,
		"status": task.status,
		"is_billable": cint(task.custom_is_billable),
		"expected_time": flt(task.expected_time),
		"actual_time": hours,
		"variance": hours - flt(task.expected_time),
		"billable_hours": billable,
		"non_billable_hours": hours - billable,
		"billing_amount": amount,
		# An emitted root's real parent is outside the emitted set; leaving it
		# populated makes the datatable look for a row that is not there.
		"parent_task": "" if task.name in root_names else (task.parent_task or ""),
		"indent": task.indent,
	}


def _columns():
	return [
		{
			"label": _("Work Item"),
			"fieldname": "work_item",
			"fieldtype": "Link",
			"options": "Task",
			"width": 260,
			"is_tree": True,
		},
		{"label": _("Subject"), "fieldname": "subject", "fieldtype": "Data", "width": 200},
		{"label": _("Type"), "fieldname": "work_item_type", "fieldtype": "Data", "width": 90},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Billable"), "fieldname": "is_billable", "fieldtype": "Check", "width": 80},
		{"label": _("Est Hours"), "fieldname": "expected_time", "fieldtype": "Float", "width": 100},
		{"label": _("Actual Hours"), "fieldname": "actual_time", "fieldtype": "Float", "width": 100},
		{"label": _("Variance"), "fieldname": "variance", "fieldtype": "Float", "width": 100},
		{"label": _("Billable Hours"), "fieldname": "billable_hours", "fieldtype": "Float", "width": 110},
		{
			"label": _("Non-Billable Hours"),
			"fieldname": "non_billable_hours",
			"fieldtype": "Float",
			"width": 130,
		},
		{"label": _("Amount"), "fieldname": "billing_amount", "fieldtype": "Currency", "width": 120},
	]
