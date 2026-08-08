import frappe


def execute():
	# The Story Budget fields on Additional Hours Request are display-only -
	# they're served live to approvers by get_story_hour_summary and never
	# stored, because "only approvers of this Project" is a Project User flag
	# that no field permlevel can express. An earlier revision briefly stored
	# (and backfilled) them; wipe those rows so nothing readable through list
	# view, report or the API survives.
	frappe.db.sql(
		"""
		update `tabAdditional Hours Request`
		set story = null, story_expected_hours = 0, story_allocated_hours = 0, story_buffer_hours = 0
		where story is not null or story_expected_hours or story_allocated_hours or story_buffer_hours
		"""
	)
