import frappe

# employment_type is mandatory on this bench through a site-level Property Setter
# (Employee-employment_type-reqd, owner Administrator, no module) - not through
# core and not through this app - and the site carries no Employment Type records
# at all, so every Employee fixture in this suite has to bring its own.
#
# Lives here rather than being repeated per module because eight fixtures across
# seven test files were all broken by that same one line of drift. Same reason
# make_project passes project_type: mandatory-by-Property-Setter is a property of
# the bench, and the fixtures have to satisfy it wherever it appears.
TEST_EMPLOYMENT_TYPE = "SZJ Test Employment"


def ensure_test_employment_type():
	# IntegrationTestCase rolls back per class, so this is re-created as often as
	# it is dropped - the exists() check is what makes it safe to call from every
	# fixture rather than once globally.
	if not frappe.db.exists("Employment Type", TEST_EMPLOYMENT_TYPE):
		frappe.get_doc({"doctype": "Employment Type", "employee_type_name": TEST_EMPLOYMENT_TYPE}).insert(
			ignore_permissions=True
		)

	return TEST_EMPLOYMENT_TYPE
