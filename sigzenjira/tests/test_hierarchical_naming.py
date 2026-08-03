import re

import frappe
from frappe.tests import IntegrationTestCase

from .test_status_cascade import make_task_under_story


def make_task(subject, work_item_type, parent_task=None, expected_time=0):
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_work_item_type": work_item_type,
			"parent_task": parent_task,
			"expected_time": expected_time,
		}
	)
	doc.insert()
	return doc


class TestHierarchicalNaming(IntegrationTestCase):
	def test_name_spells_out_the_lineage(self):
		epic = make_task("NM Epic", "Epic", expected_time=20)
		story = make_task("NM Story", "Story", epic.name, expected_time=10)
		task = make_task_under_story(story, "NM Task", 4)
		sub = make_task("NM Sub", "Sub-task", task.name)

		self.assertRegex(epic.name, r"^E-\d{3}$")
		self.assertEqual(story.name, f"{epic.name}-S-001")
		self.assertEqual(task.name, f"{story.name}-T-001")
		self.assertEqual(sub.name, f"{task.name}-ST-001")
		# every leaf still carries its root
		self.assertTrue(sub.name.startswith(epic.name))

	def test_counter_is_per_parent(self):
		epic = make_task("NM2 Epic", "Epic", expected_time=40)
		story_a = make_task("NM2 Story A", "Story", epic.name, expected_time=20)
		story_b = make_task("NM2 Story B", "Story", epic.name, expected_time=20)

		self.assertEqual(story_a.name, f"{epic.name}-S-001")
		self.assertEqual(story_b.name, f"{epic.name}-S-002")

		# each Story restarts its own Task counter at 001
		self.assertEqual(make_task_under_story(story_a, "NM2 A-T1", 2).name, f"{story_a.name}-T-001")
		self.assertEqual(make_task_under_story(story_a, "NM2 A-T2", 2).name, f"{story_a.name}-T-002")
		self.assertEqual(make_task_under_story(story_b, "NM2 B-T1", 2).name, f"{story_b.name}-T-001")

	def test_standalone_story_falls_back_to_a_global_counter(self):
		story = make_task("NM3 Orphan Story", "Story", expected_time=5)
		self.assertRegex(story.name, r"^S-\d{3}$")
		self.assertEqual(make_task_under_story(story, "NM3 T", 2).name, f"{story.name}-T-001")

	def test_reparenting_does_not_rename(self):
		story = make_task("NM4 Story", "Story", expected_time=40)
		task_a = make_task_under_story(story, "NM4 Task A", 2)
		task_b = make_task_under_story(story, "NM4 Task B", 2)
		sub = make_task("NM4 Sub", "Sub-task", task_a.name)

		sub.parent_task = task_b.name
		sub.save()

		# name is a birth certificate, not a live path
		self.assertEqual(sub.name, f"{task_a.name}-ST-001")

	def test_name_fits_the_column(self):
		epic = make_task("NM5 Epic", "Epic", expected_time=20)
		story = make_task("NM5 Story", "Story", epic.name, expected_time=10)
		task = make_task_under_story(story, "NM5 Task", 4)
		sub = make_task("NM5 Sub", "Sub-task", task.name)
		self.assertLessEqual(len(sub.name), 140)
		self.assertTrue(re.fullmatch(r"[-A-Za-z0-9]+", sub.name))
