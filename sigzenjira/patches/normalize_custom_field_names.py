import frappe


def execute():
	# Custom Field autonames to "{dt}-{fieldname}" (custom_field.py:autoname).
	# Two of ours (Task-work_item_type, Task-extra_hours) kept docnames from
	# before the fields were renamed to the custom_ prefix, and fixtures were
	# exported from a site carrying those stale names. On any site where the
	# rows are correctly named, the fixture import tries to INSERT the stale
	# name instead of updating, and Custom Field.validate rejects it with
	# "A field with the name X already exists in Y" - aborting migrate.
	#
	# Renamed by raw SQL: the docname is a bare primary key here, no Link field
	# in any doctype points at Custom Field, so there is nothing to cascade.
	for row in frappe.get_all("Custom Field", fields=["name", "dt", "fieldname"]):
		expected = f"{row.dt}-{row.fieldname}"
		if row.name == expected or frappe.db.exists("Custom Field", expected):
			continue
		frappe.db.sql("UPDATE `tabCustom Field` SET name = %s WHERE name = %s", (expected, row.name))

	frappe.clear_cache()
