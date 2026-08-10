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


def generate_split_tasks(story):
	"""Fire the per-row Create action for every ungenerated Task Split row.

	Saving a Story never turns its rows into Tasks - filling in Expected Hours
	only stores the plan - so a test that needs the real generated Tasks has to
	ask for them the same way the grid's Create button does. Reloads the Story
	so row.generated_task is populated on the caller's copy.
	"""
	from sigzenjira.events.task import create_task_from_split_row

	for row in story.custom_task_task_split:
		if not row.generated_task:
			create_task_from_split_row(row.name)

	story.reload()
	return story
