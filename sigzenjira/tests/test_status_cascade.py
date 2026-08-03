import frappe
from frappe.tests import IntegrationTestCase


def make_task(subject, work_item_type, parent_task=None, expected_time=0, status="Open", is_billable=0):
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_work_item_type": work_item_type,
			"parent_task": parent_task,
			"expected_time": expected_time,
			"status": status,
			"custom_is_billable": is_billable,
		}
	)
	doc.insert()
	return doc


def make_task_under_story(story, task_item, expected_hours=0, status="Open", is_billable=0):
	# A Story's Tasks come only from its Task Split grid
	# (custom/task.py:block_manual_task_under_story) - appending a row and
	# saving is the only supported way to put a Task under a Story, so every
	# test that used to pass a Story straight to make_task goes through here.
	story.append(
		"custom_task_split",
		{"task_item": task_item, "expected_hours": expected_hours, "is_billable": is_billable},
	)
	story.save()
	story.reload()

	row = next(r for r in story.custom_task_split if r.task_item == task_item)
	task = frappe.get_doc("Task", row.generated_task)

	if status != "Open":
		task.status = status
		task.save()

	return task


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

		t1 = make_task_under_story(story1, "PH7 S1-T1", 2)
		t2 = make_task_under_story(story1, "PH7 S1-T2", 2)
		s1 = make_task("PH7 S1T1-Sub1", "Sub-task", t1.name)
		s2 = make_task("PH7 S1T1-Sub2", "Sub-task", t1.name)

		t3 = make_task_under_story(story2, "PH7 S2-T1", 2)

		# T1 has two sub-tasks, both still Open: T1 must not auto-complete.
		self.assertEqual(status_of(t1.name), "Open")

		set_status(s1.name, "Completed")
		self.assertEqual(status_of(t1.name), "Working")  # s2 still open -> partial progress

		set_status(s2.name, "Completed")
		self.assertEqual(status_of(t1.name), "Completed")  # both subs done -> Task auto-completes
		self.assertEqual(status_of(story1.name), "Working")  # T2 still open, Story must not complete yet

		set_status(t2.name, "Completed")
		self.assertEqual(status_of(story1.name), "Completed")  # both Tasks done -> Story auto-completes
		self.assertEqual(status_of(epic.name), "Working")  # Story-2 still open

		set_status(t3.name, "Completed")
		self.assertEqual(status_of(story2.name), "Completed")
		self.assertEqual(status_of(epic.name), "Completed")  # both Stories done -> Epic auto-completes

		# Reopen a leaf sub-task -> must un-complete the whole chain back up.
		set_status(s1.name, "Working")
		self.assertEqual(status_of(t1.name), "Working")
		self.assertEqual(status_of(story1.name), "Working")
		self.assertEqual(status_of(epic.name), "Working")

	def test_manual_status_edit_on_a_parent_is_overruled(self):
		story = make_task("PH7 Manual Story", "Story", expected_time=4)
		task = make_task_under_story(story, "PH7 Manual Task", 4)

		set_status(task.name, "Working")
		self.assertEqual(status_of(story.name), "Working")

		# PM drags the Story back to Open by hand while its Task is Working.
		set_status(story.name, "Open")
		self.assertEqual(status_of(story.name), "Working")

		# Forward to Completed is core's own guard (depends_on), not ours.
		with self.assertRaises(frappe.ValidationError):
			set_status(story.name, "Completed")

		# A leaf keeps its manual status - nothing below it to derive from.
		set_status(task.name, "Pending Review")
		self.assertEqual(status_of(task.name), "Pending Review")

	def test_story_stays_working_while_a_split_row_is_ungenerated(self):
		story = make_task("PH7 Split Story", "Story", expected_time=0)
		story.append("custom_task_split", {"task_item": "Done bit", "expected_hours": 3})
		story.append("custom_task_split", {"task_item": "Not costed yet"})  # no hours -> no Task
		story.save()

		generated = frappe.get_all("Task", filters={"parent_task": story.name}, pluck="name")
		self.assertEqual(len(generated), 1)

		set_status(generated[0], "Completed")
		# Every existing child is done, but one split row never became a Task.
		self.assertEqual(status_of(story.name), "Working")

	def test_task_with_no_subtasks_is_never_auto_touched(self):
		story = make_task("PH7 Leaf Story", "Story", expected_time=5)
		task = make_task_under_story(story, "PH7 Leaf Task", 5, status="Working")
		# No sub-tasks under this Task at all - nothing should force it to Completed.
		self.assertEqual(status_of(task.name), "Working")

		set_status(task.name, "Completed")
		# Story has exactly one Task, now Completed -> Story auto-completes too.
		self.assertEqual(status_of(story.name), "Completed")
