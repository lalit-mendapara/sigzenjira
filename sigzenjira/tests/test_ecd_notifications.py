import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.permission.project_user import ecd_alert_manager_emails

MANAGER = "test_ecd_manager@example.com"
MEMBER = "test_ecd_member@example.com"


def ensure_user(email, first_name, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
	return email


def make_project(name, user_rows=None):
	if frappe.db.exists("Project", name):
		frappe.delete_doc("Project", name, force=True, ignore_permissions=True)
	project = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": name,
			# Mandatory on this bench via a Property Setter, not app code.
			"project_type": "Internal",
			"users": [
				{
					"user": row["user"],
					# Every Check field set explicitly - one omitted from the dict
					# comes back as 1, not 0.
					"custom_project_user_allocate_hours": row.get("custom_project_user_allocate_hours", 0),
					"custom_project_user_assign_users": row.get("custom_project_user_assign_users", 0),
					"custom_project_user_approve_extra_hours": row.get(
						"custom_project_user_approve_extra_hours", 0
					),
				}
				for row in (user_rows or [])
			],
		}
	)
	project.insert(ignore_permissions=True)
	return project


class TestEcdAlertManagerEmails(IntegrationTestCase):
	def test_returns_only_flagged_project_users(self):
		manager = ensure_user(MANAGER, "ECD Manager", ["Employee"])
		member = ensure_user(MEMBER, "ECD Member", ["Employee"])
		project = make_project(
			"ECD Alert CC Project",
			[
				{"user": manager, "custom_project_user_approve_extra_hours": 1},
				{"user": member, "custom_project_user_approve_extra_hours": 0},
			],
		)
		self.assertEqual(ecd_alert_manager_emails(project.name), manager)

	def test_joins_multiple_managers_with_commas(self):
		manager = ensure_user(MANAGER, "ECD Manager", ["Employee"])
		project = make_project(
			"ECD Alert CC Multi Project",
			[
				{"user": manager, "custom_project_user_approve_extra_hours": 1},
				{"user": "Administrator", "custom_project_user_approve_extra_hours": 1},
			],
		)
		self.assertCountEqual(ecd_alert_manager_emails(project.name).split(","), [manager, "Administrator"])

	def test_empty_string_for_no_project(self):
		# Tasks may have no Project at all - the cc template must render to
		# nothing rather than blowing up the whole alert.
		self.assertEqual(ecd_alert_manager_emails(None), "")

	def test_empty_string_for_project_with_no_approvers(self):
		member = ensure_user(MEMBER, "ECD Member", ["Employee"])
		project = make_project(
			"ECD Alert CC Empty Project",
			[{"user": member, "custom_project_user_approve_extra_hours": 0}],
		)
		self.assertEqual(ecd_alert_manager_emails(project.name), "")


from frappe.utils import add_days, nowdate

from sigzenjira.setup import create_ecd_notifications

TASK_STAGES = {
	"Task ECD Due Tomorrow": 1,
	"Task ECD Due Today": 0,
	"Task ECD Overdue": -1,
}
ISSUE_STAGES = {
	"Issue ECD Due Tomorrow": 1,
	"Issue ECD Due Today": 0,
	"Issue ECD Overdue": -1,
}


class TestEcdAlertNotifications(IntegrationTestCase):
	def setUp(self):
		# Per-test, not setUpClass: IntegrationTestCase rolls the transaction
		# back after each test, which would undo a class-level insert. The
		# function is idempotent, so re-running it costs nothing.
		create_ecd_notifications()

	def _make_task(self, subject, status, exp_end_date):
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": subject,
				# A parentless "Task" is legal - OPTIONAL_PARENT_TYPES in
				# events/task.py allows Story and Task to stand alone.
				"custom_task_work_item_type": "Task",
				"status": status,
				"exp_end_date": exp_end_date,
			}
		)
		task.insert(ignore_permissions=True)
		return task

	def _make_issue(self, subject, status, ecd):
		issue = frappe.get_doc(
			{
				"doctype": "Issue",
				"subject": subject,
				"status": status,
				"custom_issue_ecd": ecd,
			}
		)
		issue.insert(ignore_permissions=True)
		return issue

	def _documents_for_today(self, notification_name):
		return [d.name for d in frappe.get_doc("Notification", notification_name).get_documents_for_today()]

	def _assert_only_stage_selects(self, stages, docname, offset):
		# The document is dated nowdate() + offset, so exactly the record whose
		# offset matches must pick it up, and the other two must not.
		for notification_name, stage_offset in stages.items():
			selected = self._documents_for_today(notification_name)
			if stage_offset == offset:
				self.assertIn(docname, selected, f"{notification_name} should select {docname}")
			else:
				self.assertNotIn(docname, selected, f"{notification_name} should not select {docname}")

	def test_task_dated_tomorrow_only_hits_due_tomorrow(self):
		task = self._make_task("ECD task due tomorrow", "Open", add_days(nowdate(), 1))
		self._assert_only_stage_selects(TASK_STAGES, task.name, 1)

	def test_task_dated_today_only_hits_due_today(self):
		task = self._make_task("ECD task due today", "Open", nowdate())
		self._assert_only_stage_selects(TASK_STAGES, task.name, 0)

	def test_task_dated_yesterday_only_hits_overdue(self):
		task = self._make_task("ECD task overdue", "Open", add_days(nowdate(), -1))
		self._assert_only_stage_selects(TASK_STAGES, task.name, -1)

	def test_issue_dated_tomorrow_only_hits_due_tomorrow(self):
		issue = self._make_issue("ECD issue due tomorrow", "Open", add_days(nowdate(), 1))
		self._assert_only_stage_selects(ISSUE_STAGES, issue.name, 1)

	def test_issue_dated_today_only_hits_due_today(self):
		issue = self._make_issue("ECD issue due today", "Open", nowdate())
		self._assert_only_stage_selects(ISSUE_STAGES, issue.name, 0)

	def test_issue_dated_yesterday_only_hits_overdue(self):
		issue = self._make_issue("ECD issue overdue", "Open", add_days(nowdate(), -1))
		self._assert_only_stage_selects(ISSUE_STAGES, issue.name, -1)

	def test_terminal_status_task_selected_by_no_stage(self):
		for status, offset in (("Completed", 1), ("Completed", 0), ("Cancelled", -1)):
			task = self._make_task(f"ECD {status} task {offset}", status, add_days(nowdate(), offset))
			for notification_name in TASK_STAGES:
				self.assertNotIn(task.name, self._documents_for_today(notification_name))

	def test_terminal_status_issue_selected_by_no_stage(self):
		for status, offset in (("Resolved", 1), ("Closed", 0), ("Closed", -1)):
			issue = self._make_issue(f"ECD {status} issue {offset}", status, add_days(nowdate(), offset))
			for notification_name in ISSUE_STAGES:
				self.assertNotIn(issue.name, self._documents_for_today(notification_name))

	def test_record_settings(self):
		expected = {
			"Task ECD Due Tomorrow": ("Task", "exp_end_date", "Days Before", 1),
			"Task ECD Due Today": ("Task", "exp_end_date", "Days After", 0),
			"Task ECD Overdue": ("Task", "exp_end_date", "Days After", 1),
			"Issue ECD Due Tomorrow": ("Issue", "custom_issue_ecd", "Days Before", 1),
			"Issue ECD Due Today": ("Issue", "custom_issue_ecd", "Days After", 0),
			"Issue ECD Overdue": ("Issue", "custom_issue_ecd", "Days After", 1),
		}
		for name, (doctype, date_field, event, days) in expected.items():
			notification = frappe.get_doc("Notification", name)
			self.assertEqual(notification.document_type, doctype)
			self.assertEqual(notification.date_changed, date_field)
			self.assertEqual(notification.event, event)
			self.assertEqual(notification.days_in_advance, days)
			# One record drives both the mail and the bell.
			self.assertEqual(notification.channel, "Email")
			self.assertEqual(notification.send_system_notification, 1)
			self.assertEqual(notification.send_to_all_assignees, 1)
			self.assertEqual(notification.enabled, 1)
			# Managers ride along as CC on every stage.
			self.assertEqual(len(notification.recipients), 1)
			self.assertIn("ecd_alert_manager_emails", notification.recipients[0].cc)

	def test_create_is_idempotent(self):
		names = list(TASK_STAGES) + list(ISSUE_STAGES)
		self.assertEqual(frappe.db.count("Notification", {"name": ("in", names)}), 6)
		create_ecd_notifications()
		self.assertEqual(frappe.db.count("Notification", {"name": ("in", names)}), 6)
