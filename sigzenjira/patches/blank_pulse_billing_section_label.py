import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	# hide_pulse_billable_fields cleared the depends_on on pulse_sigzen's
	# "Billing Hours Details" Section Break, which freed core's department /
	# is_active / percent_complete from being hidden along with it. It could not
	# hide the Section Break itself for that same reason - those three core
	# fields sit inside it, because pulse ends its Project chain with a section
	# it never closes.
	#
	# So the section still renders, now holding only core fields under a heading
	# about billing. Blank the label and it reads as a plain divider. Reversed by
	# deleting this Property Setter, same as the rest of the pause.
	if not frappe.db.exists("Custom Field", "Project-custom_section_break_billing_details"):
		return

	make_property_setter("Project", "custom_section_break_billing_details", "label", "", "Data")
	frappe.clear_cache(doctype="Project")
