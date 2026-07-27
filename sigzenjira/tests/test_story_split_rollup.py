import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase


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


class TestStorySplitRollup(IntegrationTestCase):
	def test_story_expected_time_is_derived_from_split_rows(self):
		epic = make_task("SR Epic", "Epic", expected_time=10)
		story = make_task("SR Story", "Story", epic.name)  # no expected_time given

		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4})
		story.append("custom_task_split", {"task_item": "T2", "expected_hours": 5})
		story.save()

		self.assertEqual(story.expected_time, 9)

	def test_split_rollup_exceeding_epic_budget_is_blocked(self):
		epic = make_task("SR Over Epic", "Epic", expected_time=5)
		story = make_task("SR Over Story", "Story", epic.name)

		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 3})
		story.append("custom_task_split", {"task_item": "T2", "expected_hours": 4})
		with self.assertRaises(frappe.ValidationError):
			story.save()

	def test_generated_task_defaults_to_story_priority(self):
		epic = make_task("SR Prio Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Prio Story",
				"custom_work_item_type": "Story",
				"parent_task": epic.name,
				"priority": "High",
			}
		)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4})
		story.insert()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task
		self.assertEqual(frappe.db.get_value("Task", generated_task, "priority"), "High")

	def test_approved_additional_hours_reflect_in_split_row(self):
		epic = make_task("SR AHR Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR AHR Story",
				"custom_work_item_type": "Story",
				"parent_task": epic.name,
			}
		)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4})
		story.insert()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task

		ahr = frappe.get_doc(
			{
				"doctype": "Additional Hours Request",
				"task": generated_task,
				"additional_hours_requested": 2,
				"reason": "split rollup test",
			}
		)
		ahr.insert()
		apply_workflow(ahr.as_dict(), "Submit")
		ahr.reload()
		apply_workflow(ahr.as_dict(), "Approve")

		story.reload()
		self.assertEqual(story.custom_task_split[0].extra_hours, 2)

	def test_task_expected_time_edit_reflects_in_split_row(self):
		epic = make_task("SR Edit Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Edit Story",
				"custom_work_item_type": "Story",
				"parent_task": epic.name,
			}
		)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4})
		story.insert()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task

		task = frappe.get_doc("Task", generated_task)
		task.expected_time = 3
		task.save()

		story.reload()
		self.assertEqual(story.custom_task_split[0].expected_hours, 3)
		self.assertEqual(story.expected_time, 3)

	def test_split_row_expected_hours_edit_reflects_in_task(self):
		epic = make_task("SR Row Edit Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Row Edit Story",
				"custom_work_item_type": "Story",
				"parent_task": epic.name,
			}
		)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 3})
		story.insert()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task
		self.assertEqual(frappe.db.get_value("Task", generated_task, "expected_time"), 3)

		story.custom_task_split[0].expected_hours = 5
		story.save()

		self.assertEqual(frappe.db.get_value("Task", generated_task, "expected_time"), 5)

	def test_deleting_task_cleans_up_depends_on_and_split_row(self):
		epic = make_task("SR Del Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Del Story",
				"custom_work_item_type": "Story",
				"parent_task": epic.name,
			}
		)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 3})
		story.append("custom_task_split", {"task_item": "T2", "expected_hours": 2})
		story.insert()

		story.reload()
		t1 = story.custom_task_split[0].generated_task
		t2 = story.custom_task_split[1].generated_task

		# core's populate_depends_on auto-adds a "Task Depends On" row on the
		# Story (the parent) for each child Task created under it.
		story.reload()
		self.assertIn(t1, [row.task for row in story.depends_on])
		self.assertEqual(len(story.custom_task_split), 2)

		frappe.delete_doc("Task", t1)

		story.reload()
		self.assertNotIn(t1, [row.task for row in story.depends_on])
		self.assertEqual([row.generated_task for row in story.custom_task_split], [t2])
		self.assertEqual(story.expected_time, 2)

	def test_non_privileged_user_cannot_add_split_row(self):
		user = "test_split_row_employee@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": "Split Row Employee",
					"send_welcome_email": 0,
					"roles": [{"role": "Employee"}, {"role": "Projects User"}],
				}
			).insert(ignore_permissions=True)

		epic = make_task("SR Perm Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Perm Story",
				"custom_work_item_type": "Story",
				"parent_task": epic.name,
			}
		)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 3})
		story.insert()
		story.reload()

		frappe.set_user(user)
		try:
			story_as_employee = frappe.get_doc("Task", story.name)
			story_as_employee.append("custom_task_split", {"task_item": "T2", "expected_hours": 2})
			with self.assertRaises(frappe.ValidationError):
				story_as_employee.save()
		finally:
			frappe.set_user("Administrator")
