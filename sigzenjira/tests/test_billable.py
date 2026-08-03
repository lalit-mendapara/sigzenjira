import frappe
from frappe.tests import IntegrationTestCase

# No IGNORE_TEST_RECORD_DEPENDENCIES here: it only works for test modules inside
# a doctype folder (frappe/tests/classes/integration_test_case.py:59 raises
# NotImplementedError otherwise - see test_work_board.py for the same note).
# Not needed anyway - this test only inspects Custom Field/meta definitions,
# it never creates a Project/Issue/Employee/Timesheet document.


def make_project(name, is_billable=0):
	return frappe.get_doc(
		{"doctype": "Project", "project_name": name, "custom_is_billable": is_billable}
	).insert(ignore_permissions=True)


def make_issue(subject, project=None, is_billable=0):
	return frappe.get_doc(
		{"doctype": "Issue", "subject": subject, "project": project, "custom_is_billable": is_billable}
	).insert()


def make_task(
	subject, work_item_type, parent_task=None, project=None, expected_time=0, is_billable=0, issue=None
):
	return frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_work_item_type": work_item_type,
			"parent_task": parent_task,
			"project": project,
			"issue": issue,
			"expected_time": expected_time,
			"custom_is_billable": is_billable,
		}
	).insert()


class TestBillableFields(IntegrationTestCase):
	def test_billable_custom_fields_exist(self):
		for doctype in ("Project", "Issue", "Task"):
			self.assertTrue(
				frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": "custom_is_billable"}),
				f"custom_is_billable missing on {doctype}",
			)

	def test_billable_fields_are_checks_defaulting_to_zero(self):
		for doctype in ("Project", "Issue", "Task"):
			meta_field = frappe.get_meta(doctype).get_field("custom_is_billable")
			self.assertEqual(meta_field.fieldtype, "Check")
			self.assertEqual(meta_field.default, "0")

	def test_task_split_has_is_billable_column(self):
		meta_field = frappe.get_meta("Task Split").get_field("is_billable")
		self.assertIsNotNone(meta_field)
		self.assertEqual(meta_field.fieldtype, "Check")
		self.assertEqual(meta_field.in_list_view, 1)


class TestBillableUpwardClamp(IntegrationTestCase):
	def test_billable_subtask_under_non_billable_task_throws(self):
		# Sub-task under Task is the manual parent/child pair with no creation
		# gate - block_manual_task_under_story forbids adding a Task straight to
		# a Story, so a Task/Story pair here would throw for that reason instead
		# and the clamp would never be exercised.
		task = make_task("BC Clamp Task", "Task", expected_time=10, is_billable=0)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_task("BC Clamp Sub", "Sub-task", task.name, is_billable=1)
		self.assertIn("not billable", str(caught.exception))

	def test_billable_story_under_non_billable_epic_throws(self):
		epic = make_task("BC Clamp Epic", "Epic", expected_time=20, is_billable=0)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_task("BC Clamp Story", "Story", epic.name, expected_time=10, is_billable=1)
		self.assertIn("not billable", str(caught.exception))

	def test_billable_parent_allows_mixed_children(self):
		task = make_task("BC Mixed Task", "Task", expected_time=10, is_billable=1)

		billed = make_task("BC Billed Sub", "Sub-task", task.name, is_billable=1)
		free = make_task("BC Free Sub", "Sub-task", task.name, is_billable=0)

		self.assertEqual(billed.custom_is_billable, 1)
		self.assertEqual(free.custom_is_billable, 0)

	def test_billable_epic_under_non_billable_project_throws(self):
		project = make_project("BC Free Project", is_billable=0)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_task("BC Billed Epic", "Epic", project=project.name, is_billable=1)
		self.assertIn("not billable", str(caught.exception))

	def test_billable_issue_under_non_billable_project_throws(self):
		project = make_project("BC Free Project 2", is_billable=0)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_issue("BC Billed Issue", project=project.name, is_billable=1)
		self.assertIn("not billable", str(caught.exception))

	def test_story_clamps_against_its_issue_not_just_its_project(self):
		# The post-delivery support case: Project stays billable, the support
		# Issue is deliberately unbilled. A nearest-source rule would resolve to
		# the still-billable Project and let this through.
		project = make_project("BC Support Project", is_billable=1)
		issue = make_issue("BC Free Support", project=project.name, is_billable=0)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_task("BC Support Story", "Story", project=project.name, issue=issue.name, is_billable=1)
		self.assertIn("not billable", str(caught.exception))

	def test_billable_split_row_under_non_billable_story_throws(self):
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Split Clamp Story",
				"custom_work_item_type": "Story",
				"custom_is_billable": 0,
			}
		)
		story.append("custom_task_split", {"task_item": "Billed work", "is_billable": 1})

		with self.assertRaises(frappe.ValidationError) as caught:
			story.insert()
		self.assertIn("marked Billable", str(caught.exception))
