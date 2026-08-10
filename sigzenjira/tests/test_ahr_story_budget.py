import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase

from sigzenjira.sigzenjira.doctype.additional_hours_request.additional_hours_request import (
	get_hour_summary,
	get_story_hour_summary,
)
from sigzenjira.tests import generate_split_tasks
from sigzenjira.tests.test_project_user_permission_helper import ensure_user, make_project

APPROVER = "test_ahr_budget_approver@example.com"
REQUESTER = "test_ahr_budget_requester@example.com"
OUTSIDE_PM = "test_ahr_outside_pm@example.com"


def make_task(subject, work_item_type, parent_task=None, expected_time=0, project=None):
	return frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_task_work_item_type": work_item_type,
			"parent_task": parent_task,
			"expected_time": expected_time,
			"project": project,
		}
	).insert()


class TestAHRStoryBudget(IntegrationTestCase):
	def setUp(self):
		# Both hold Projects Manager, so the only difference between them is the
		# custom_project_user_approve_extra_hours flag - which is exactly what the gate tests.
		# (ERPNext strips the Employee role off a user with no Employee record,
		# so Employee alone would leave them without doctype access at all.)
		self.approver = ensure_user(APPROVER, "AHR Budget Approver", ["Employee", "Projects Manager"])
		self.requester = ensure_user(REQUESTER, "AHR Budget Requester", ["Employee"])
		# Deliberately on no Project at all - the role alone must not be enough.
		self.outside_pm = ensure_user(OUTSIDE_PM, "AHR Outside PM", ["Employee", "Projects Manager"])
		# make_project's own dedupe keys on the docname (PROJ-xxxx), not
		# project_name, so a fixed name would collide across tests.
		self.project = make_project(
			f"AHR Budget {self._testMethodName}",
			[
				{"user": self.approver, "custom_project_user_approve_extra_hours": 1},
				{"user": self.requester},
			],
		)

		epic = make_task("AHR Budget Epic", "Epic", expected_time=50, project=self.project.name)
		self.story = make_task("AHR Budget Story", "Story", epic.name, project=self.project.name)
		self.story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		self.story.save()
		self.story.reload()
		self.story.expected_time = 10
		self.story.save()
		generate_split_tasks(self.story)
		self.task = self.story.custom_task_task_split[0].generated_task

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_approver_sees_expected_allocated_and_buffer(self):
		frappe.set_user(self.approver)
		summary = get_story_hour_summary(self.task)

		self.assertEqual(summary["story"], self.story.name)
		self.assertEqual(summary["story_expected_hours"], 10)
		self.assertEqual(summary["story_allocated_hours"], 4)
		self.assertEqual(summary["story_buffer_hours"], 6)

	def test_project_user_without_the_approve_flag_sees_nothing(self):
		frappe.set_user(self.requester)
		summary = get_story_hour_summary(self.task)

		self.assertIsNone(summary["story"])
		self.assertEqual(summary["story_buffer_hours"], 0)

	def test_approved_extra_hours_count_as_allocated(self):
		ahr = frappe.get_doc(
			{
				"doctype": "Additional Hours Request",
				"task": self.task,
				"requested_by": self.requester,
				"additional_hours_requested": 2,
				"reason": "extra hours eat the buffer",
			}
		).insert()
		apply_workflow(ahr.as_dict(), "Submit")
		ahr.reload()
		apply_workflow(ahr.as_dict(), "Approve")

		frappe.set_user(self.approver)
		summary = get_story_hour_summary(self.task)

		self.assertEqual(summary["story_expected_hours"], 10)
		self.assertEqual(summary["story_allocated_hours"], 6)
		self.assertEqual(summary["story_buffer_hours"], 4)

	def _pending_request(self, reason):
		ahr = frappe.get_doc(
			{
				"doctype": "Additional Hours Request",
				"task": self.task,
				"requested_by": self.requester,
				"additional_hours_requested": 2,
				"reason": reason,
			}
		).insert()
		apply_workflow(ahr.as_dict(), "Submit")
		ahr.reload()
		return ahr

	def _marked_approved(self, ahr):
		doc = frappe.get_doc("Additional Hours Request", ahr.name)
		doc.status = "Approved"
		return doc

	def test_projects_manager_off_the_project_cannot_approve(self):
		# Role alone used to be a blanket bypass on this doctype - a Projects
		# Manager on no Project could see and approve every request in the org,
		# including ones they were never notified about in the first place.
		ahr = self._pending_request("outside PM approval attempt")

		frappe.set_user(self.outside_pm)
		self.assertFalse(frappe.has_permission("Additional Hours Request", "write", doc=ahr.name))
		with self.assertRaises(frappe.PermissionError):
			self._marked_approved(ahr).validate_approver()

	def test_project_user_with_the_approve_flag_can_approve(self):
		ahr = self._pending_request("flagged approver approval")

		frappe.set_user(self.approver)
		self.assertTrue(frappe.has_permission("Additional Hours Request", "write", doc=ahr.name))
		self._marked_approved(ahr).validate_approver()

	def test_standalone_task_has_no_story_budget(self):
		task = make_task("AHR Standalone Task", "Task", expected_time=3, project=self.project.name)

		frappe.set_user(self.approver)
		self.assertIsNone(get_story_hour_summary(task.name)["story"])

	def test_task_hours_are_visible_without_the_approve_flag(self):
		# The requester raising the request reads their own Task's numbers -
		# only the Story budget half is approver-gated.
		ahr = frappe.get_doc(
			{
				"doctype": "Additional Hours Request",
				"task": self.task,
				"requested_by": self.requester,
				"additional_hours_requested": 2,
				"reason": "task hours visibility",
			}
		).insert()
		apply_workflow(ahr.as_dict(), "Submit")
		ahr.reload()
		apply_workflow(ahr.as_dict(), "Approve")

		frappe.set_user(self.requester)
		summary = get_hour_summary(self.task)

		self.assertIsNone(summary["story"])
		self.assertEqual(summary["task_allocated_hours"], 4)
		self.assertEqual(summary["task_actual_hours"], 0)
		# 4 estimated + the 2 just approved.
		self.assertEqual(summary["task_total_hours"], 6)

	def test_task_hour_summary_is_never_stored_on_the_request(self):
		ahr = frappe.get_doc(
			{
				"doctype": "Additional Hours Request",
				"task": self.task,
				"requested_by": self.requester,
				"additional_hours_requested": 2,
				"reason": "task hour storage test",
				"task_allocated_hours": 4,
				"task_actual_hours": 1,
				"task_total_hours": 5,
			}
		).insert()

		self.assertEqual(ahr.task_allocated_hours, 0)
		self.assertEqual(ahr.task_actual_hours, 0)
		self.assertEqual(ahr.task_total_hours, 0)

	def test_summary_is_never_stored_on_the_request(self):
		# Display-only: a stored value would be readable by the requester
		# through list view/report, which is exactly what the approver-only
		# gate above exists to prevent.
		ahr = frappe.get_doc(
			{
				"doctype": "Additional Hours Request",
				"task": self.task,
				"requested_by": self.requester,
				"additional_hours_requested": 2,
				"reason": "story budget storage test",
				"story": self.story.name,
				"story_expected_hours": 10,
				"story_allocated_hours": 4,
				"story_buffer_hours": 6,
			}
		).insert()

		self.assertIsNone(ahr.story)
		self.assertEqual(ahr.story_expected_hours, 0)
		self.assertEqual(ahr.story_allocated_hours, 0)
		self.assertEqual(ahr.story_buffer_hours, 0)
