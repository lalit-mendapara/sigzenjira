import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase
from frappe.utils import flt


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


def extra_hours(task_name):
	return flt(frappe.db.get_value("Task", task_name, "custom_extra_hours"))


def make_ahr(task_name, hours, reason="phase6 test"):
	doc = frappe.get_doc(
		{
			"doctype": "Additional Hours Request",
			"task": task_name,
			"additional_hours_requested": hours,
			"reason": reason,
		}
	)
	doc.insert()
	return doc


def approve(ahr_doc):
	ahr_doc.reload()
	apply_workflow(ahr_doc.as_dict(), "Submit")
	ahr_doc.reload()
	return apply_workflow(ahr_doc.as_dict(), "Approve")


def reject(ahr_doc):
	ahr_doc.reload()
	apply_workflow(ahr_doc.as_dict(), "Submit")
	ahr_doc.reload()
	return apply_workflow(ahr_doc.as_dict(), "Reject")


class TestPhase6Regression(IntegrationTestCase):
	def test_01_full_worked_hierarchy(self):
		epic = make_task("PH6 Epic", "Epic", expected_time=10)
		story1 = make_task("PH6 Story-1", "Story", epic.name, expected_time=4)
		story2 = make_task("PH6 Story-2", "Story", epic.name, expected_time=6)

		t1 = make_task("PH6 S1-T1", "Task", story1.name, expected_time=2)
		make_task("PH6 S1-T2", "Task", story1.name, expected_time=2)

		s2t1 = make_task("PH6 S2-T1", "Task", story2.name, expected_time=1)
		make_task("PH6 S2-T2", "Task", story2.name, expected_time=3)
		make_task("PH6 S2-T3", "Task", story2.name, expected_time=2)

		self.assertEqual(extra_hours(epic.name), 0)

		# Phase 3 budget-violation cases, still blocked at Phase 6 gate
		with self.assertRaises(frappe.ValidationError):
			make_task("PH6 Story-3", "Story", epic.name, expected_time=1)

		with self.assertRaises(frappe.ValidationError):
			make_task("PH6 S2-T4", "Task", story2.name, expected_time=1)

		# editing an existing Task's expected_time upward past budget is blocked too
		t1.reload()
		t1.expected_time = 3  # would make Story-1 total 5h > its 4h budget
		with self.assertRaises(frappe.ValidationError):
			t1.save()

		# Sub-task: no expected_time required, no budget check applies
		make_task("PH6 SubTask", "Sub-task", s2t1.name, expected_time=0)
		make_task("PH6 SubTask over budget?", "Sub-task", s2t1.name, expected_time=999)

	def test_02_hierarchy_edge_cases(self):
		epic = make_task("PH6 H Epic", "Epic", expected_time=5)

		with self.assertRaises(frappe.ValidationError):
			make_task("PH6 Epic with parent", "Epic", epic.name, expected_time=1)

		story = make_task("PH6 H Story", "Story", epic.name, expected_time=5)

		with self.assertRaises(frappe.ValidationError):
			# Task's parent must be a Story, not an Epic
			make_task("PH6 Task under Epic", "Task", epic.name, expected_time=1)

		task = make_task("PH6 H Task", "Task", story.name, expected_time=5)

		with self.assertRaises(frappe.ValidationError):
			# Sub-task's parent must be a Task, not a Story
			make_task("PH6 Subtask under Story", "Sub-task", story.name)

		make_task("PH6 H Subtask", "Sub-task", task.name)

		# standalone Story/Task with no parent are allowed
		make_task("PH6 Standalone Story", "Story", expected_time=1)
		make_task("PH6 Standalone Task", "Task", expected_time=1)

	def test_03_rollup_and_reject(self):
		epic = make_task("PH6 R Epic", "Epic", expected_time=10)
		story = make_task("PH6 R Story", "Story", epic.name, expected_time=6)
		t1 = make_task("PH6 R T1", "Task", story.name, expected_time=1)
		make_task("PH6 R T2", "Task", story.name, expected_time=3)
		make_task("PH6 R T3", "Task", story.name, expected_time=2)

		ahr1 = make_ahr(t1.name, 2)
		approve(ahr1)
		self.assertEqual(extra_hours(t1.name), 2)
		self.assertEqual(extra_hours(story.name), 2)
		self.assertEqual(extra_hours(epic.name), 2)

		t2 = frappe.db.get_value("Task", {"subject": "PH6 R T2"})
		ahr2 = make_ahr(t2, 1)
		approve(ahr2)
		self.assertEqual(extra_hours(story.name), 3)
		self.assertEqual(extra_hours(epic.name), 3)

		ahr3 = make_ahr(t1.name, 5)
		reject(ahr3)
		self.assertEqual(extra_hours(t1.name), 2)
		self.assertEqual(extra_hours(story.name), 3)
		self.assertEqual(extra_hours(epic.name), 3)

	def test_04_pre_existing_task_without_work_item_type(self):
		# Simulates a Task created before this customization existed: insert
		# bypassing the (now-mandatory) custom_work_item_type, the way a
		# pre-migration row would already sit in the DB with it blank.
		doc = frappe.get_doc({"doctype": "Task", "subject": "PH6 Legacy Task (no type)"})
		doc.flags.ignore_mandatory = True
		doc.insert()
		self.assertFalse(frappe.db.get_value("Task", doc.name, "custom_work_item_type"))

		# Opening it (just a read) must not error.
		reloaded = frappe.get_doc("Task", doc.name)
		self.assertEqual(reloaded.subject, "PH6 Legacy Task (no type)")

		# Editing/saving it without classifying is correctly blocked by the
		# mandatory field, not a crash.
		reloaded.description = "touched"
		with self.assertRaises(frappe.ValidationError):
			reloaded.save()

	def test_05_extra_hours_approver_gets_notified_on_submit(self):
		approver = "test_ahr_approver@example.com"
		if not frappe.db.exists("User", approver):
			frappe.get_doc(
				{"doctype": "User", "email": approver, "first_name": "AHR Approver", "send_welcome_email": 0}
			).insert(ignore_permissions=True)

		project = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": "PH6 Notify Project",
				"users": [{"user": approver, "custom_approve_extra_hours": 1}],
			}
		).insert(ignore_permissions=True)

		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "PH6 Notify Task",
				"custom_work_item_type": "Task",
				"project": project.name,
				"expected_time": 2,
			}
		)
		task.insert()

		frappe.db.delete("Notification Log", {"document_type": "Additional Hours Request"})

		ahr = make_ahr(task.name, 1)
		apply_workflow(ahr.as_dict(), "Submit")

		notifications = frappe.get_all(
			"Notification Log", filters={"document_type": "Additional Hours Request", "for_user": approver}
		)
		self.assertEqual(len(notifications), 1)
