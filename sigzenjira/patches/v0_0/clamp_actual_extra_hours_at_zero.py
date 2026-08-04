import frappe


def execute():
	# Actual Extra Hours is overrun only; rows written before the clamp can hold
	# a negative (under-budget) value.
	frappe.db.sql(
		"update `tabTask` set custom_actual_extra_hours = 0 where custom_actual_extra_hours < 0"
	)
