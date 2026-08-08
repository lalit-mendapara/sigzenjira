import frappe

PERM_FLAG_FIELDS = [
	"permlevel",
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"print",
	"email",
	"report",
	"import",
	"export",
	"share",
	"if_owner",
]


def create_custom_docperms():
	create_task_projects_manager_docperm()
	create_task_costing_permlevel_docperms()
	create_task_template_director_po_docperm()
	create_task_template_employee_docperm()


def create_task_projects_manager_docperm():
	# Core Task ships permission rows for Projects User, HR User, HR Manager
	# only — Projects Manager (the Additional Hours Request approver role)
	# has none, so without this they can't even open the Task linked to a
	# request they're approving/rejecting.
	# The instant a Custom DocPerm exists for a doctype, Frappe ignores ALL
	# of its standard DocPerm rows (frappe/model/meta.py get_permissions) —
	# so just adding Projects Manager here would silently strip Task access
	# from every role core already grants it to (Projects User, HR User, HR
	# Manager). Mirror those into Custom DocPerm first so nothing regresses.
	for perm in frappe.get_all("DocPerm", filters={"parent": "Task"}, fields=["role", *PERM_FLAG_FIELDS]):
		if frappe.db.exists(
			"Custom DocPerm", {"parent": "Task", "role": perm.role, "permlevel": perm.permlevel}
		):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Task",
				"parenttype": "DocType",
				"parentfield": "permissions",
				**perm,
			}
		).insert(ignore_permissions=True)

	if frappe.db.exists("Custom DocPerm", {"parent": "Task", "role": "Projects Manager"}):
		return

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": "Task",
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": "Projects Manager",
			"read": 1,
			"write": 1,
			"create": 1,
			"delete": 0,
			"report": 1,
			"export": 1,
		}
	).insert(ignore_permissions=True)


COSTING_PERMLEVEL_ROLES = ("Projects Manager", "Director", "Product Owner")


def create_task_costing_permlevel_docperms():
	# Who may read the permlevel-1 costing fields (property_setter.py:
	# set_task_costing_permlevel). Director and Product Owner already hold full
	# permlevel-0 CRUD on Task and bypass project scoping entirely - hiding what a
	# task cost from the two roles whose remit IS the whole org was an oversight,
	# not a policy.
	# Read/export only: the numbers are ERPNext rollups from Timesheets, nothing
	# should be hand-edited here.
	for role in COSTING_PERMLEVEL_ROLES:
		if frappe.db.exists("Custom DocPerm", {"parent": "Task", "role": role, "permlevel": 1}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Task",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"permlevel": 1,
				"read": 1,
				"export": 1,
			}
		).insert(ignore_permissions=True)


def create_task_template_director_po_docperm():
	# Task Template ships permission rows for Projects Manager, System
	# Manager, Projects User only — Director and Product Owner (both allowed
	# to set any Work Item Type, including Story) have none, so without this
	# they can't create a Task Template or even select one in a Story's
	# Task Template picker. Same Custom DocPerm gotcha as
	# create_task_projects_manager_docperm above: mirror existing rows first.
	for perm in frappe.get_all(
		"DocPerm", filters={"parent": "Task Template"}, fields=["role", *PERM_FLAG_FIELDS]
	):
		if frappe.db.exists(
			"Custom DocPerm", {"parent": "Task Template", "role": perm.role, "permlevel": perm.permlevel}
		):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Task Template",
				"parenttype": "DocType",
				"parentfield": "permissions",
				**perm,
			}
		).insert(ignore_permissions=True)

	for role in ("Director", "Product Owner"):
		if frappe.db.exists("Custom DocPerm", {"parent": "Task Template", "role": role}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "Task Template",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": role,
				"read": 1,
				"write": 1,
				"create": 1,
				"delete": 1,
				"report": 1,
				"export": 1,
				"share": 1,
				"email": 1,
				"print": 1,
			}
		).insert(ignore_permissions=True)


def create_task_template_employee_docperm():
	# Employee needs to SELECT an existing Task Template on a Story (see
	# validate_employee_story_field_restriction, events/task.py) but must
	# never create/edit/delete one - read only, no create/write/delete.
	if frappe.db.exists("Custom DocPerm", {"parent": "Task Template", "role": "Employee"}):
		return

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": "Task Template",
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": "Employee",
			"read": 1,
			"write": 0,
			"create": 0,
			"delete": 0,
		}
	).insert(ignore_permissions=True)
