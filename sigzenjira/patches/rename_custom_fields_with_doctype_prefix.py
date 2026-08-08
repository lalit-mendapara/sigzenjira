import json

import frappe

# Every Custom Field this app owns was renamed to carry its doctype:
# custom_<doctype>_<name>. Fixtures only insert and update, so on an existing
# site the OLD column and the OLD Custom Field row would both survive the
# fixture import - the new field would be created empty alongside the populated
# old one, and every Task would read Billable = 0. This patch is what carries
# the data across; it must run before sync_fixtures, which it does (patches run
# at frappe/migrate.py:144, fixtures at :171).
RENAMES = [
	("Project User", "custom_allocate_hours", "custom_project_user_allocate_hours"),
	("Project User", "custom_assign_users", "custom_project_user_assign_users"),
	("Project User", "custom_approve_extra_hours", "custom_project_user_approve_extra_hours"),
	("Project User", "custom_set_work_item_type", "custom_project_user_set_work_item_type"),
	("Project", "custom_is_billable", "custom_project_is_billable"),
	("Issue", "custom_is_billable", "custom_issue_is_billable"),
	("Task", "custom_is_billable", "custom_task_is_billable"),
	("Task", "custom_work_item_type", "custom_task_work_item_type"),
	("Task", "custom_billing_hours_section", "custom_task_billing_hours_section"),
	("Task", "custom_billable_hours", "custom_task_billable_hours"),
	("Task", "custom_non_billable_hours", "custom_task_non_billable_hours"),
	("Task", "custom_story_budget_is_manual", "custom_task_story_budget_is_manual"),
	("Task", "custom_extra_hours", "custom_task_extra_hours"),
	("Task", "custom_actual_extra_hours", "custom_task_actual_extra_hours"),
	("Task", "custom_issue_type", "custom_task_issue_type"),
	("Task", "custom_split_work_section", "custom_task_split_work_section"),
	("Task", "custom_task_template", "custom_task_task_template"),
	("Task", "custom_task_split", "custom_task_task_split"),
	("Task", "custom_epic_budget_is_manual", "custom_task_epic_budget_is_manual"),
	("Task", "custom_split_work_tab", "custom_task_split_work_tab"),
]

# Table-type fields: child rows carry the old fieldname in `parentfield`, and a
# stale value there makes the grid come up empty even though the rows exist.
# Keyed on the NEW fieldname - that is what repoint_child_parentfield looks up.
TABLE_FIELDS = {("Task", "custom_task_task_split"): "Task Split"}


def execute():
	for doctype, old, new in RENAMES:
		rename_column(doctype, old, new)
		rename_custom_field(doctype, old, new)
		repoint_property_setters(doctype, old, new)
		repoint_child_parentfield(doctype, old, new)

	frappe.clear_cache()


def rename_column(doctype, old, new):
	# Guarded both ways so the patch is a no-op on a site that already renamed
	# (or on a fresh site, where after_install created the new name directly).
	if not frappe.db.has_column(doctype, old):
		return
	if frappe.db.has_column(doctype, new):
		return
	frappe.db.rename_column(doctype, old, new)


def rename_custom_field(doctype, old, new):
	name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": old})
	if not name:
		return

	frappe.db.set_value("Custom Field", name, "fieldname", new, update_modified=False)

	# Custom Field autonames to "{dt}-{fieldname}", so the docname is now stale.
	# Renamed by raw SQL for the same reason normalize_custom_field_names does
	# it: the docname is a bare primary key, nothing Links to Custom Field.
	expected = f"{doctype}-{new}"
	if name != expected and not frappe.db.exists("Custom Field", expected):
		frappe.db.sql("UPDATE `tabCustom Field` SET name = %s WHERE name = %s", (expected, name))

	# Other custom fields on the same doctype that order themselves after this one.
	frappe.db.set_value(
		"Custom Field", {"dt": doctype, "insert_after": old}, "insert_after", new, update_modified=False
	)


def repoint_property_setters(doctype, old, new):
	for ps in frappe.get_all(
		"Property Setter",
		filters={"doc_type": doctype},
		fields=["name", "field_name", "property", "value"],
	):
		updates = {}

		if ps.field_name == old:
			updates["field_name"] = new

		# field_order is a JSON list of fieldnames; insert_after / depends_on
		# hold one fieldname (or an expression mentioning it).
		if ps.property == "field_order" and ps.value:
			try:
				order = json.loads(ps.value)
			except ValueError:
				order = None
			if isinstance(order, list) and old in order:
				updates["value"] = json.dumps([new if f == old else f for f in order])
		elif ps.value and old in ps.value:
			updates["value"] = ps.value.replace(old, new)

		if not updates:
			continue

		frappe.db.set_value("Property Setter", ps.name, updates, update_modified=False)

		# Property Setter autonames to "{doc_type}-{field_name}-{property}".
		if "field_name" in updates:
			expected = f"{doctype}-{new}-{ps.property}"
			if ps.name != expected and not frappe.db.exists("Property Setter", expected):
				frappe.db.sql(
					"UPDATE `tabProperty Setter` SET name = %s WHERE name = %s", (expected, ps.name)
				)


def repoint_child_parentfield(doctype, old, new):
	child_doctype = TABLE_FIELDS.get((doctype, new))
	if not child_doctype:
		return
	frappe.db.sql(
		f"update `tab{child_doctype}` set parentfield = %s where parenttype = %s and parentfield = %s",
		(new, doctype, old),
	)
