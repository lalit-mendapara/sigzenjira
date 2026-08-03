import json

import frappe
from frappe.desk.form import assign_to
from frappe.tests import IntegrationTestCase

from sigzenjira.custom.task import set_split_row_assignees


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


class TestTaskSplitAssignEcd(IntegrationTestCase):
	def test_generation_seeds_task_ecd(self):
		epic = make_task("AE Gen Epic", "Epic", expected_time=10)
		story = make_task("AE Gen Story", "Story", epic.name)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4, "ecd": "2026-08-20"})
		story.save()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task
		self.assertIsNotNone(generated_task)

		task = frappe.get_doc("Task", generated_task)
		self.assertEqual(str(task.exp_end_date).split(" ")[0], "2026-08-20")

	def test_split_row_ecd_edit_pushes_to_task(self):
		epic = make_task("AE Push Epic", "Epic", expected_time=10)
		story = make_task("AE Push Story", "Story", epic.name)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task

		story.custom_task_split[0].ecd = "2026-09-01"
		story.save()

		task = frappe.get_doc("Task", generated_task)
		self.assertEqual(str(task.exp_end_date).split(" ")[0], "2026-09-01")

	def test_task_ecd_edit_pulls_to_split_row(self):
		epic = make_task("AE Pull Epic", "Epic", expected_time=10)
		story = make_task("AE Pull Story", "Story", epic.name)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task

		task = frappe.get_doc("Task", generated_task)
		task.exp_end_date = "2026-09-10"
		task.save()

		story.reload()
		self.assertEqual(str(story.custom_task_split[0].ecd), "2026-09-10")

	def test_task_assignment_via_sidebar_pushes_to_split_row_assign_display(self):
		epic = make_task("AE Assign Epic", "Epic", expected_time=10)
		story = make_task("AE Assign Story", "Story", epic.name)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task

		assign_to.add({"assign_to": ["Administrator"], "doctype": "Task", "name": generated_task})

		story.reload()
		self.assertIn("Administrator", story.custom_task_split[0].assign)

		assign_to.remove("Task", generated_task, "Administrator")

		story.reload()
		self.assertEqual(story.custom_task_split[0].assign, "")

	def test_set_split_row_assignees_api(self):
		epic = make_task("AE API Epic", "Epic", expected_time=10)
		story = make_task("AE API Story", "Story", epic.name)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()

		story.reload()
		row_name = story.custom_task_split[0].name
		generated_task = story.custom_task_split[0].generated_task

		set_split_row_assignees(row_name, frappe.as_json(["Administrator"]))

		assigned = frappe.get_all(
			"ToDo",
			filters={"reference_type": "Task", "reference_name": generated_task, "status": "Open"},
			pluck="allocated_to",
		)
		self.assertIn("Administrator", assigned)

		set_split_row_assignees(row_name, frappe.as_json([]))

		assigned_after = frappe.get_all(
			"ToDo",
			filters={
				"reference_type": "Task",
				"reference_name": generated_task,
				"allocated_to": "Administrator",
				"status": "Open",
			},
		)
		self.assertEqual(assigned_after, [])

	def test_pending_assign_applied_in_same_save_as_generation(self):
		epic = make_task("AE Pending Same Save Epic", "Epic", expected_time=10)
		story = make_task("AE Pending Same Save Story", "Story", epic.name)
		story.append(
			"custom_task_split",
			{"task_item": "T1", "expected_hours": 4, "pending_assign_users": json.dumps(["Administrator"])},
		)
		story.save()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task
		self.assertIsNotNone(generated_task)

		assigned = frappe.get_all(
			"ToDo",
			filters={"reference_type": "Task", "reference_name": generated_task, "status": "Open"},
			pluck="allocated_to",
		)
		self.assertIn("Administrator", assigned)
		self.assertFalse(story.custom_task_split[0].pending_assign_users)

	def test_pending_assign_staged_before_generation_then_applied(self):
		epic = make_task("AE Pending Later Epic", "Epic", expected_time=10)
		story = make_task("AE Pending Later Story", "Story", epic.name)
		story.append(
			"custom_task_split",
			{"task_item": "T1", "pending_assign_users": json.dumps(["Administrator"])},
		)
		story.save()

		story.reload()
		self.assertIsNone(story.custom_task_split[0].generated_task)

		story.custom_task_split[0].expected_hours = 4
		story.save()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task
		self.assertIsNotNone(generated_task)

		assigned = frappe.get_all(
			"ToDo",
			filters={"reference_type": "Task", "reference_name": generated_task, "status": "Open"},
			pluck="allocated_to",
		)
		self.assertIn("Administrator", assigned)

	def test_deleting_generated_task_removes_its_row_and_never_regenerates(self):
		epic = make_task("AE Regen Epic", "Epic", expected_time=10)
		story = make_task("AE Regen Story", "Story", epic.name)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()

		story.reload()
		generated_task = story.custom_task_split[0].generated_task

		frappe.delete_doc("Task", generated_task)

		story.reload()
		self.assertEqual(len(story.custom_task_split), 0)

		# Saving again must not resurrect the line the deletion removed.
		story.save()

		story.reload()
		self.assertEqual(len(story.custom_task_split), 0)

	def test_backfill_patch_populates_existing_rows(self):
		epic = make_task("AE Backfill Epic", "Epic", expected_time=10)
		story = make_task("AE Backfill Story", "Story", epic.name)
		story.append("custom_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()

		story.reload()
		row_name = story.custom_task_split[0].name
		generated_task = story.custom_task_split[0].generated_task

		task = frappe.get_doc("Task", generated_task)
		task.exp_end_date = "2026-09-15"
		task.save()

		assign_to.add({"assign_to": ["Administrator"], "doctype": "Task", "name": generated_task})

		# Simulate the pre-feature state this patch exists to fix: a row
		# whose ecd/assign never got written because it was generated
		# before this feature's live sync hooks existed.
		frappe.db.set_value("Task Split", row_name, {"ecd": None, "assign": ""})

		from sigzenjira.patches.v0_0.backfill_task_split_assign_ecd import execute

		execute()

		story.reload()
		row = story.custom_task_split[0]
		self.assertEqual(str(row.ecd), "2026-09-15")
		self.assertIn("Administrator", row.assign)
