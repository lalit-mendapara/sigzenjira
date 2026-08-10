import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.events.task import create_task_from_split_row, get_task_split_permissions

GRANTED_USER = "test_wit_granted@example.com"


def ensure_user():
	if not frappe.db.exists("User", GRANTED_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": GRANTED_USER,
				"first_name": "Work Item Type Grantee",
				"send_welcome_email": 0,
				"roles": [{"role": "Employee"}, {"role": "Projects User"}],
			}
		).insert(ignore_permissions=True)
	return GRANTED_USER


def make_project(project_name, granted, billable=False):
	# Project autonames to PROJ-####, so the lookup has to go through
	# project_name (which carries the unique index) rather than the docname.
	existing = frappe.db.get_value("Project", {"project_name": project_name})
	if existing:
		frappe.delete_doc("Project", existing, force=True, ignore_permissions=True)
	return frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": project_name,
			# reqd on this bench (Customize Form), not in core erpnext.
			"project_type": "Internal",
			"custom_project_is_billable": 1 if billable else 0,
			"users": [{"user": GRANTED_USER, "custom_project_user_set_work_item_type": 1 if granted else 0}],
		}
	).insert(ignore_permissions=True)


class TestWorkItemTypeProjectGrant(IntegrationTestCase):
	def setUp(self):
		self.user = ensure_user()
		self.granted = make_project("WIT Granted Project", granted=True)
		self.plain = make_project("WIT Plain Project", granted=False)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_flagged_user_can_create_story_on_that_project(self):
		frappe.set_user(self.user)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "WIT Granted Story",
				"custom_task_work_item_type": "Story",
				"project": self.granted.name,
			}
		)
		story.insert()
		self.assertEqual(frappe.db.get_value("Task", story.name, "custom_task_work_item_type"), "Story")

	def test_same_user_blocked_on_a_project_without_the_flag(self):
		frappe.set_user(self.user)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "WIT Plain Story",
				"custom_task_work_item_type": "Story",
				"project": self.plain.name,
			}
		)
		with self.assertRaises(frappe.ValidationError):
			story.insert()

	def test_sub_task_still_open_to_everyone(self):
		frappe.set_user(self.user)
		parent = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "WIT Granted Parent Task",
				"custom_task_work_item_type": "Task",
				"project": self.granted.name,
			}
		).insert()

		# Under the project the user was NOT granted on - Sub-task is the one
		# classification that never needs the grant.
		sub = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "WIT Sub-task",
				"custom_task_work_item_type": "Sub-task",
				"parent_task": parent.name,
				"project": self.plain.name,
			}
		)
		sub.insert()
		self.assertEqual(frappe.db.get_value("Task", sub.name, "custom_task_work_item_type"), "Sub-task")

	def test_flagged_user_can_edit_the_story_afterwards(self):
		# Creating a Story is pointless if validate_employee_story_field_restriction
		# then locks the creator out of every field but the template.
		frappe.set_user(self.user)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "WIT Editable Story",
				"custom_task_work_item_type": "Story",
				"project": self.granted.name,
			}
		).insert()

		story.subject = "WIT Editable Story renamed"
		story.save()
		self.assertEqual(frappe.db.get_value("Task", story.name, "subject"), "WIT Editable Story renamed")

	def test_set_work_item_type_grant_alone_allows_create_task_from_split(self):
		# The row-level "Create Task" escape hatch takes either grant -
		# Allocate Hours or Set Work Item Type. This user has only the latter.
		frappe.set_user(self.user)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "WIT Split Story",
				"custom_task_work_item_type": "Story",
				"project": self.granted.name,
				"custom_task_task_split": [{"task_item": "Design"}],
			}
		).insert()

		task_name = create_task_from_split_row(story.custom_task_task_split[0].name)
		self.assertEqual(frappe.db.get_value("Task", task_name, "parent_task"), story.name)

	def test_split_row_inheriting_the_storys_billable_flag_is_not_a_billable_edit(self):
		# Adding a row to a saved billable Story seeds is_billable=1 from the
		# Story (task.js custom_task_split_add). That's inherited, not chosen -
		# same carve-out validate_billable_edit_permission already makes for a
		# new doc under a billable parent.
		billable = make_project("WIT Billable Project", granted=True, billable=True)
		frappe.set_user(self.user)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "WIT Billable Story",
				"custom_task_work_item_type": "Story",
				"project": billable.name,
				"custom_task_is_billable": 1,
			}
		).insert()

		story.append("custom_task_task_split", {"task_item": "Design", "is_billable": 1})
		story.save()
		self.assertEqual(len(frappe.get_doc("Task", story.name).custom_task_task_split), 1)

	def test_neither_grant_blocks_create_task_from_split(self):
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "WIT Plain Split Story",
				"custom_task_work_item_type": "Story",
				"project": self.plain.name,
				"custom_task_task_split": [{"task_item": "Design"}],
			}
		).insert(ignore_permissions=True)

		frappe.set_user(self.user)
		with self.assertRaises(frappe.ValidationError):
			create_task_from_split_row(story.custom_task_task_split[0].name)

	def test_story_edit_still_locked_without_the_grant(self):
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "WIT Locked Story",
				"custom_task_work_item_type": "Story",
				"project": self.plain.name,
			}
		).insert(ignore_permissions=True)

		frappe.set_user(self.user)
		as_user = frappe.get_doc("Task", story.name)
		as_user.subject = "WIT Locked Story renamed"
		with self.assertRaises(frappe.ValidationError):
			as_user.save()

	def test_client_permission_payload_reports_the_grant(self):
		frappe.set_user(self.user)
		self.assertTrue(get_task_split_permissions(self.granted.name)["set_work_item_type"])
		self.assertFalse(get_task_split_permissions(self.plain.name)["set_work_item_type"])
		self.assertFalse(get_task_split_permissions(None)["set_work_item_type"])
