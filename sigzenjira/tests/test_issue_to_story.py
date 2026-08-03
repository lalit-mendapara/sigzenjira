import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.custom.issue import make_story

from .test_status_cascade import make_task_under_story


def make_issue(subject="Test Issue", issue_type=None, priority=None, project=None):
	doc = frappe.get_doc(
		{
			"doctype": "Issue",
			"subject": subject,
			"issue_type": issue_type,
			"priority": priority,
			"project": project,
		}
	)
	doc.insert()
	return doc


class TestIssueToStory(IntegrationTestCase):
	def test_make_story_creates_orphan_story_linked_to_issue(self):
		issue = make_issue("Login page broken")

		task_name = make_story(issue.name)
		task = frappe.get_doc("Task", task_name)

		self.assertEqual(task.custom_work_item_type, "Story")
		self.assertEqual(task.issue, issue.name)
		self.assertIsNone(task.parent_task or None)

	def test_make_story_fetches_issue_type(self):
		if not frappe.db.exists("Issue Type", "Bug"):
			frappe.get_doc({"doctype": "Issue Type", "name": "Bug"}).insert()

		issue = make_issue("Crash on save", issue_type="Bug")
		task = frappe.get_doc("Task", make_story(issue.name))

		self.assertEqual(task.custom_issue_type, "Bug")

	def test_make_story_maps_project_from_issue(self):
		project = frappe.get_doc({"doctype": "Project", "project_name": "Issue2Story Project"}).insert(
			ignore_permissions=True
		)
		issue = make_issue("Needs project mapped", project=project.name)

		task = frappe.get_doc("Task", make_story(issue.name))

		self.assertEqual(task.project, project.name)

	def test_only_one_story_per_issue(self):
		issue = make_issue("Duplicate story attempt")
		make_story(issue.name)

		with self.assertRaises(frappe.ValidationError):
			make_story(issue.name)

	def test_story_completion_resolves_linked_issue(self):
		issue = make_issue("Resolve me")
		task = frappe.get_doc("Task", make_story(issue.name))

		task.status = "Completed"
		task.save()

		self.assertEqual(frappe.db.get_value("Issue", issue.name, "status"), "Resolved")

	def test_cascade_completion_does_not_resolve_issue(self):
		issue = make_issue("Cascade should not resolve")
		story = frappe.get_doc("Task", make_story(issue.name))

		# A Story's Tasks come only from its Task Split grid
		# (custom/task.py:block_manual_task_under_story) - same fix as
		# test_status_cascade.py and friends.
		make_task_under_story(story, "Sub piece", expected_hours=1, status="Completed")

		self.assertEqual(frappe.db.get_value("Task", story.name, "status"), "Completed")
		self.assertNotEqual(frappe.db.get_value("Issue", issue.name, "status"), "Resolved")
