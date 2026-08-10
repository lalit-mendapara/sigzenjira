import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.tests import generate_split_tasks

ISSUE_ECD = "2026-08-20"
LATE = "2026-08-25"
EARLY = "2026-08-15"


def make_issue(subject):
	return frappe.get_doc({"doctype": "Issue", "subject": subject, "custom_issue_ecd": ISSUE_ECD}).insert()


def make_task(subject, work_item_type, parent_task=None, expected_time=0, issue=None):
	return frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_task_work_item_type": work_item_type,
			"parent_task": parent_task,
			"expected_time": expected_time,
			"issue": issue,
		}
	).insert()


class TestIssueEcdGuard(IntegrationTestCase):
	def test_task_ecd_past_issue_ecd_is_refused(self):
		issue = make_issue("ECD Guard Own")
		story = make_task("ECD Guard Own Story", "Story", issue=issue.name)

		story.exp_end_date = LATE
		self.assertRaises(frappe.ValidationError, story.save)

		story.reload()
		story.exp_end_date = EARLY
		story.save()
		self.assertEqual(str(story.exp_end_date).split(" ")[0], EARLY)

	def test_split_row_ecd_past_issue_ecd_is_refused(self):
		issue = make_issue("ECD Guard Row")
		story = make_task("ECD Guard Row Story", "Story", issue=issue.name)

		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4, "ecd": LATE})
		self.assertRaises(frappe.ValidationError, story.save)

		story.reload()
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4, "ecd": EARLY})
		story.save()
		self.assertEqual(str(story.custom_task_task_split[0].ecd), EARLY)

	def test_generated_task_inherits_the_issue_ecd_of_its_story(self):
		# The generated Task links no Issue of its own - the guard has to walk up
		# to the Story to find the date it is bound by.
		issue = make_issue("ECD Guard Generated")
		story = make_task("ECD Guard Generated Story", "Story", issue=issue.name)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4, "ecd": EARLY})
		story.save()

		generate_split_tasks(story)
		task = frappe.get_doc("Task", story.custom_task_task_split[0].generated_task)

		task.exp_end_date = LATE
		self.assertRaises(frappe.ValidationError, task.save)

		sub_task = make_task("ECD Guard Sub-task", "Sub-task", parent_task=task.name)
		sub_task.exp_end_date = LATE
		self.assertRaises(frappe.ValidationError, sub_task.save)

	def test_an_existing_breach_does_not_lock_the_record(self):
		# A date that was already past the Issue ECD before the rule existed must
		# stay editable for everything except the date itself.
		issue = make_issue("ECD Guard Legacy")
		story = make_task("ECD Guard Legacy Story", "Story", issue=issue.name)
		frappe.db.set_value("Task", story.name, "exp_end_date", LATE, update_modified=False)

		story.reload()
		story.status = "Working"
		story.save()

		self.assertEqual(story.status, "Working")
