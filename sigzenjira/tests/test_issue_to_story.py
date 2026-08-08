import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.events.issue import make_story



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

		self.assertEqual(task.custom_task_work_item_type, "Story")
		self.assertEqual(task.issue, issue.name)
		self.assertIsNone(task.parent_task or None)

	def test_make_story_fetches_issue_type(self):
		if not frappe.db.exists("Issue Type", "Bug"):
			frappe.get_doc({"doctype": "Issue Type", "name": "Bug"}).insert()

		issue = make_issue("Crash on save", issue_type="Bug")
		task = frappe.get_doc("Task", make_story(issue.name))

		self.assertEqual(task.custom_task_issue_type, "Bug")

	def test_make_story_maps_project_from_issue(self):
		project = frappe.get_doc({"doctype": "Project", "project_name": "Issue2Story Project"}).insert(
			ignore_permissions=True
		)
		issue = make_issue("Needs project mapped", project=project.name)

		task = frappe.get_doc("Task", make_story(issue.name))

		self.assertEqual(task.project, project.name)

	def test_issue_description_edit_syncs_to_story(self):
		issue = make_issue("Description follows the Issue")
		story = make_story(issue.name)

		issue.description = "<p>Updated from the ticket</p>"
		issue.save()

		self.assertEqual(
			frappe.db.get_value("Task", story, "description"), "<p>Updated from the ticket</p>"
		)

	def test_only_one_story_per_issue(self):
		issue = make_issue("Duplicate story attempt")
		make_story(issue.name)

		with self.assertRaises(frappe.ValidationError):
			make_story(issue.name)

	def test_story_completion_leaves_issue_status_alone(self):
		issue = make_issue("Resolve me")
		task = frappe.get_doc("Task", make_story(issue.name))

		task.status = "Completed"
		task.save()

		self.assertNotEqual(frappe.db.get_value("Issue", issue.name, "status"), "Resolved")
