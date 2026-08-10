import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

# pulse_sigzen ships a parallel billable/non-billable implementation on the same
# doctypes: its own custom_billable_hours / custom_nonbillable_hours per
# Timesheet Detail row, totalled onto Project and Task. sigzenjira computes the
# same split off core's is_billable / billing_hours instead, so with both
# installed a user sees two sets of billable figures that disagree.
#
# Hidden by Property Setter rather than deleted: the columns and their data stay
# untouched, and deleting these Property Setters brings pulse's fields straight
# back. Nothing in pulse_sigzen is edited - it is a shared team repo.
#
# pulse's server logic needs no switching off either. Every branch of it keys
# off Project.custom_is_billable, a different field from sigzenjira's
# custom_project_is_billable: its Timesheet Detail flag is
# fetch_from project.custom_is_billable, validate_billable_timesheet_rows only
# throws when that flag is 1, and its rollups guard every write with
# `if billable_delta:`. Left at 0, none of it fires.
HIDE = {
	"Project": [
		"custom_is_billable",
		"custom_total_billable_hrs",
		"custom_total_nonbillable_hrs",
	],
	"Timesheet": [
		"custom_section_break_timesheet_billing_details",
		"custom_total_billable_hrs",
		"custom_total_nonbillable_hrs",
	],
	"Timesheet Detail": [
		"custom_is_billable",
		"custom_billable_hours",
		"custom_nonbillable_hours",
	],
	"Task": [
		"custom_section_break_task_billing_details",
		"custom_task_total_billable_hours",
		"custom_task_total_nonbillable_hours",
	],
}


def execute():
	if "pulse_sigzen" not in frappe.get_installed_apps():
		return

	for doctype, fieldnames in HIDE.items():
		for fieldname in fieldnames:
			if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname}):
				make_property_setter(doctype, fieldname, "hidden", 1, "Check")

	# The one pulse Section Break that must NOT be hidden. It is never closed
	# before core's department / is_active / percent_complete, so those three sit
	# inside it and would disappear with it - the same swallowing that
	# move_project_is_billable_out_of_pulse_section had to move this app's own
	# field out of. Clearing its depends_on instead leaves an empty collapsible
	# section and frees the core fields it was gating.
	#
	# The two hour fields inside it are hidden by the loop above, so the section
	# renders empty rather than showing pulse's numbers.
	if frappe.db.exists("Custom Field", "Project-custom_section_break_billing_details"):
		make_property_setter("Project", "custom_section_break_billing_details", "depends_on", "", "Code")

	for doctype in HIDE:
		frappe.clear_cache(doctype=doctype)
