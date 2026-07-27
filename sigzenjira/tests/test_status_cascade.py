import frappe
from frappe.tests import IntegrationTestCase


def make_task(subject, work_item_type, parent_task=None, expected_time=0, status="Open"):
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_work_item_type": work_item_type,
			"parent_task": parent_task,
			"expected_time": expected_time,
			"status": status,
		}
	)
	doc.insert()
	return doc


def set_status(task_name, status):
	doc = frappe.get_doc("Task", task_name)
	doc.status = status
	doc.save()


def status_of(task_name):
	return frappe.db.get_value("Task", task_name, "status")


class TestStatusCascade(IntegrationTestCase):
	def test_full_cascade_up_and_reopen(self):
		epic = make_task("PH7 Epic", "Epic", expected_time=20)
		story1 = make_task("PH7 Story-1", "Story", epic.name, expected_time=10)
		story2 = make_task("PH7 Story-2", "Story", epic.name, expected_time=10)

		t1 = make_task("PH7 S1-T1", "Task", story1.name, expected_time=2)
		t2 = make_task("PH7 S1-T2", "Task", story1.name, expected_time=2)
		s1 = make_task("PH7 S1T1-Sub1", "Sub-task", t1.name)
		s2 = make_task("PH7 S1T1-Sub2", "Sub-task", t1.name)

		t3 = make_task("PH7 S2-T1", "Task", story2.name, expected_time=2)

		# T1 has two sub-tasks, both still Open: T1 must not auto-complete.
		self.assertEqual(status_of(t1.name), "Open")

		set_status(s1.name, "Completed")
		self.assertEqual(status_of(t1.name), "Open")  # s2 still open

		set_status(s2.name, "Completed")
		self.assertEqual(status_of(t1.name), "Completed")  # both subs done -> Task auto-completes
		self.assertEqual(status_of(story1.name), "Open")  # T2 still open, Story must not complete yet

		set_status(t2.name, "Completed")
		self.assertEqual(status_of(story1.name), "Completed")  # both Tasks done -> Story auto-completes
		self.assertEqual(status_of(epic.name), "Open")  # Story-2 still open

		set_status(t3.name, "Completed")
		self.assertEqual(status_of(story2.name), "Completed")
		self.assertEqual(status_of(epic.name), "Completed")  # both Stories done -> Epic auto-completes

		# Reopen a leaf sub-task -> must un-complete the whole chain back up.
		set_status(s1.name, "Working")
		self.assertEqual(status_of(t1.name), "Open")
		self.assertEqual(status_of(story1.name), "Open")
		self.assertEqual(status_of(epic.name), "Open")

	def test_task_with_no_subtasks_is_never_auto_touched(self):
		story = make_task("PH7 Leaf Story", "Story", expected_time=5)
		task = make_task("PH7 Leaf Task", "Task", story.name, expected_time=5, status="Working")
		# No sub-tasks under this Task at all - nothing should force it to Completed.
		self.assertEqual(status_of(task.name), "Working")

		set_status(task.name, "Completed")
		# Story has exactly one Task, now Completed -> Story auto-completes too.
		self.assertEqual(status_of(story.name), "Completed")
