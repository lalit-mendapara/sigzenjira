import frappe
from frappe.tests import IntegrationTestCase

from .test_status_cascade import make_task_under_story


def make_task(subject, work_item_type, parent_task=None, expected_time=0):
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_task_work_item_type": work_item_type,
			"parent_task": parent_task,
			"expected_time": expected_time,
		}
	)
	doc.insert()
	return doc


class TestActualTimeReparent(IntegrationTestCase):
	def test_epic_actual_time_updates_when_story_attached_later(self):
		epic = make_task("RP Epic", "Epic", expected_time=50)
		story = make_task("RP Story", "Story", expected_time=20)  # standalone at first
		task = make_task_under_story(story, "RP Task", 10)

		frappe.db.set_value("Task", task.name, "actual_time", 3, update_modified=False)
		frappe.db.set_value("Task", story.name, "actual_time", 3, update_modified=False)

		self.assertEqual(frappe.db.get_value("Task", epic.name, "actual_time"), 0)

		story.reload()
		story.parent_task = epic.name
		story.save()

		self.assertEqual(frappe.db.get_value("Task", epic.name, "actual_time"), 3)

		# but it can't be moved back out again - the parent is frozen once set
		story.reload()
		story.parent_task = None
		self.assertRaises(frappe.ValidationError, story.save)

		self.assertEqual(frappe.db.get_value("Task", epic.name, "actual_time"), 3)
