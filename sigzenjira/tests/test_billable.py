import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.custom.issue import make_story
from sigzenjira.custom.task import create_task_without_hours

# No IGNORE_TEST_RECORD_DEPENDENCIES here: it only works for test modules inside
# a doctype folder (frappe/tests/classes/integration_test_case.py:59 raises
# NotImplementedError otherwise - see test_work_board.py for the same note).
# Not needed anyway - this test only inspects Custom Field/meta definitions,
# it never creates a Project/Issue/Employee/Timesheet document.


def make_project(name, is_billable=0):
	return frappe.get_doc(
		{"doctype": "Project", "project_name": name, "custom_is_billable": is_billable}
	).insert(ignore_permissions=True)


def make_issue(subject, project=None, is_billable=0):
	return frappe.get_doc(
		{"doctype": "Issue", "subject": subject, "project": project, "custom_is_billable": is_billable}
	).insert()


def make_task(
	subject, work_item_type, parent_task=None, project=None, expected_time=0, is_billable=0, issue=None
):
	return frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_work_item_type": work_item_type,
			"parent_task": parent_task,
			"project": project,
			"issue": issue,
			"expected_time": expected_time,
			"custom_is_billable": is_billable,
		}
	).insert()


class TestBillableFields(IntegrationTestCase):
	def test_billable_custom_fields_exist(self):
		for doctype in ("Project", "Issue", "Task"):
			self.assertTrue(
				frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": "custom_is_billable"}),
				f"custom_is_billable missing on {doctype}",
			)

	def test_billable_fields_are_checks_defaulting_to_zero(self):
		for doctype in ("Project", "Issue", "Task"):
			meta_field = frappe.get_meta(doctype).get_field("custom_is_billable")
			self.assertEqual(meta_field.fieldtype, "Check")
			self.assertEqual(meta_field.default, "0")

	def test_task_split_has_is_billable_column(self):
		meta_field = frappe.get_meta("Task Split").get_field("is_billable")
		self.assertIsNotNone(meta_field)
		self.assertEqual(meta_field.fieldtype, "Check")
		self.assertEqual(meta_field.in_list_view, 1)


class TestBillableUpwardClamp(IntegrationTestCase):
	def test_billable_subtask_under_non_billable_task_throws(self):
		# Sub-task under Task is the manual parent/child pair with no creation
		# gate - block_manual_task_under_story forbids adding a Task straight to
		# a Story, so a Task/Story pair here would throw for that reason instead
		# and the clamp would never be exercised.
		task = make_task("BC Clamp Task", "Task", expected_time=10, is_billable=0)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_task("BC Clamp Sub", "Sub-task", task.name, is_billable=1)
		self.assertIn("not billable", str(caught.exception))

	def test_billable_story_under_non_billable_epic_throws(self):
		epic = make_task("BC Clamp Epic", "Epic", expected_time=20, is_billable=0)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_task("BC Clamp Story", "Story", epic.name, expected_time=10, is_billable=1)
		self.assertIn("not billable", str(caught.exception))

	def test_billable_parent_allows_mixed_children(self):
		task = make_task("BC Mixed Task", "Task", expected_time=10, is_billable=1)

		billed = make_task("BC Billed Sub", "Sub-task", task.name, is_billable=1)
		free = make_task("BC Free Sub", "Sub-task", task.name, is_billable=0)

		self.assertEqual(billed.custom_is_billable, 1)
		self.assertEqual(free.custom_is_billable, 0)

	def test_billable_epic_under_non_billable_project_throws(self):
		project = make_project("BC Free Project", is_billable=0)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_task("BC Billed Epic", "Epic", project=project.name, is_billable=1)
		self.assertIn("not billable", str(caught.exception))

	def test_billable_issue_under_non_billable_project_throws(self):
		project = make_project("BC Free Project 2", is_billable=0)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_issue("BC Billed Issue", project=project.name, is_billable=1)
		self.assertIn("not billable", str(caught.exception))

	def test_story_clamps_against_its_issue_not_just_its_project(self):
		# The post-delivery support case: Project stays billable, the support
		# Issue is deliberately unbilled. A nearest-source rule would resolve to
		# the still-billable Project and let this through.
		project = make_project("BC Support Project", is_billable=1)
		issue = make_issue("BC Free Support", project=project.name, is_billable=0)

		with self.assertRaises(frappe.ValidationError) as caught:
			make_task("BC Support Story", "Story", project=project.name, issue=issue.name, is_billable=1)
		self.assertIn("not billable", str(caught.exception))

	def test_billable_split_row_under_non_billable_story_throws(self):
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Split Clamp Story",
				"custom_work_item_type": "Story",
				"custom_is_billable": 0,
			}
		)
		story.append("custom_task_split", {"task_item": "Billed work", "is_billable": 1})

		with self.assertRaises(frappe.ValidationError) as caught:
			story.insert()
		self.assertIn("marked Billable", str(caught.exception))


class TestBillableDownwardClamp(IntegrationTestCase):
	def test_unchecking_task_with_billable_subtask_throws(self):
		# Sub-task under Task is the manual parent/child pair with no creation
		# gate - block_manual_task_under_story forbids adding a Task straight to
		# a Story, so a Task/Story pair here would throw for that reason instead.
		task = make_task("BC Down Task", "Task", expected_time=10, is_billable=1)
		make_task("BC Down Sub", "Sub-task", task.name, is_billable=1)

		task.reload()
		task.custom_is_billable = 0
		with self.assertRaises(frappe.ValidationError) as caught:
			task.save()
		self.assertIn("still billable", str(caught.exception))

	def test_unchecking_task_with_only_non_billable_subtasks_succeeds(self):
		task = make_task("BC Down Free Task", "Task", expected_time=10, is_billable=1)
		make_task("BC Down Free Sub", "Sub-task", task.name, is_billable=0)

		task.reload()
		task.custom_is_billable = 0
		task.save()

		self.assertEqual(frappe.db.get_value("Task", task.name, "custom_is_billable"), 0)

	def test_unchecking_project_with_billable_issue_throws(self):
		project = make_project("BC Down Project", is_billable=1)
		make_issue("BC Down Issue", project=project.name, is_billable=1)

		project.reload()
		project.custom_is_billable = 0
		with self.assertRaises(frappe.ValidationError) as caught:
			project.save()
		self.assertIn("still billable", str(caught.exception))

	def test_unchecking_issue_with_billable_story_throws(self):
		project = make_project("BC Down Issue Project", is_billable=1)
		issue = make_issue("BC Down Billed Issue", project=project.name, is_billable=1)
		make_task("BC Down Issue Story", "Story", project=project.name, issue=issue.name, is_billable=1)

		issue.reload()
		issue.custom_is_billable = 0
		with self.assertRaises(frappe.ValidationError) as caught:
			issue.save()
		self.assertIn("still billable", str(caught.exception))

	def test_story_and_its_rows_can_be_unbilled_in_one_save(self):
		# The DB still holds is_billable=1 on the child rows while the parent's
		# validate() runs, so reading rows from the DB here would throw on a
		# save that legitimately unbills both at once.
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Down Both Story",
				"custom_work_item_type": "Story",
				"custom_is_billable": 1,
			}
		)
		story.append("custom_task_split", {"task_item": "Some work", "is_billable": 1})
		story.insert()

		story.reload()
		story.custom_is_billable = 0
		story.custom_task_split[0].is_billable = 0
		story.save()

		self.assertEqual(frappe.db.get_value("Task", story.name, "custom_is_billable"), 0)


BILLABLE_EMPLOYEE_USER = "test_billable_employee@example.com"


def ensure_billable_employee_user():
	if not frappe.db.exists("User", BILLABLE_EMPLOYEE_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": BILLABLE_EMPLOYEE_USER,
				"first_name": "Billable Employee",
				"send_welcome_email": 0,
				"roles": [{"role": "Employee"}, {"role": "Projects User"}],
			}
		).insert(ignore_permissions=True)
	return BILLABLE_EMPLOYEE_USER


class TestBillablePermission(IntegrationTestCase):
	def test_non_privileged_user_cannot_change_billable(self):
		user = ensure_billable_employee_user()
		# Parent is billable so the upward clamp cannot fire - the only thing
		# left that can throw is the permission gate under test.
		parent = make_task("BC Perm Parent", "Task", expected_time=10, is_billable=1)
		task = make_task("BC Perm Sub", "Sub-task", parent.name, is_billable=0)

		frappe.set_user(user)
		try:
			as_employee = frappe.get_doc("Task", task.name)
			as_employee.custom_is_billable = 1
			with self.assertRaises(frappe.ValidationError) as caught:
				as_employee.save()
			self.assertIn("change Billable", str(caught.exception))
		finally:
			frappe.set_user("Administrator")

	def test_non_privileged_user_can_save_unrelated_field_on_billable_task(self):
		user = ensure_billable_employee_user()
		parent = make_task("BC Perm Untouched Parent", "Task", expected_time=10, is_billable=1)
		task = make_task("BC Perm Untouched Sub", "Sub-task", parent.name, is_billable=1)

		frappe.set_user(user)
		try:
			as_employee = frappe.get_doc("Task", task.name)
			as_employee.status = "Working"
			as_employee.save()
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Task", task.name, "custom_is_billable"), 1)

	def test_privileged_role_can_change_billable(self):
		parent = make_task("BC Perm Privileged Parent", "Task", expected_time=10, is_billable=1)
		task = make_task("BC Perm Privileged Sub", "Sub-task", parent.name, is_billable=0)

		task.custom_is_billable = 1
		task.save()

		self.assertEqual(frappe.db.get_value("Task", task.name, "custom_is_billable"), 1)

	def test_non_privileged_user_cannot_change_split_row_billable(self):
		user = ensure_billable_employee_user()
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Perm Split Story",
				"custom_work_item_type": "Story",
				"custom_is_billable": 1,
			}
		)
		story.append("custom_task_split", {"task_item": "Perm item", "is_billable": 0})
		story.insert()

		frappe.set_user(user)
		try:
			as_employee = frappe.get_doc("Task", story.name)
			as_employee.custom_task_split[0].is_billable = 1
			with self.assertRaises(frappe.ValidationError) as caught:
				as_employee.save()
			self.assertIn("Task Split", str(caught.exception))
		finally:
			frappe.set_user("Administrator")


class TestBillablePropagation(IntegrationTestCase):
	def test_make_story_copies_billable_issue(self):
		project = make_project("BC Prop Billed Project", is_billable=1)
		issue = make_issue("BC Prop Billed Issue", project=project.name, is_billable=1)

		story = frappe.get_doc("Task", make_story(issue.name))

		self.assertEqual(story.custom_is_billable, 1)

	def test_make_story_copies_unbilled_support_issue(self):
		# Post-delivery support: Project still billable, this Issue is not.
		project = make_project("BC Prop Support Project", is_billable=1)
		issue = make_issue("BC Prop Support Issue", project=project.name, is_billable=0)

		story = frappe.get_doc("Task", make_story(issue.name))

		self.assertEqual(story.custom_is_billable, 0)

	def test_split_row_generates_billable_task(self):
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Prop Split Story",
				"custom_work_item_type": "Story",
				"custom_is_billable": 1,
			}
		)
		story.append("custom_task_split", {"task_item": "Billed item", "expected_hours": 3, "is_billable": 1})
		story.append("custom_task_split", {"task_item": "Free item", "expected_hours": 2, "is_billable": 0})
		story.insert()

		story.reload()
		billed_row, free_row = story.custom_task_split[0], story.custom_task_split[1]

		self.assertEqual(frappe.db.get_value("Task", billed_row.generated_task, "custom_is_billable"), 1)
		self.assertEqual(frappe.db.get_value("Task", free_row.generated_task, "custom_is_billable"), 0)

	def test_unchecking_split_row_pushes_to_generated_task(self):
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Prop Push Story",
				"custom_work_item_type": "Story",
				"custom_is_billable": 1,
			}
		)
		story.append("custom_task_split", {"task_item": "Push item", "expected_hours": 3, "is_billable": 1})
		story.insert()
		story.reload()

		story.custom_task_split[0].is_billable = 0
		story.save()

		self.assertEqual(
			frappe.db.get_value("Task", story.custom_task_split[0].generated_task, "custom_is_billable"), 0
		)

	def test_unchecking_generated_task_pulls_back_to_split_row(self):
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Prop Pull Story",
				"custom_work_item_type": "Story",
				"custom_is_billable": 1,
			}
		)
		story.append("custom_task_split", {"task_item": "Pull item", "expected_hours": 3, "is_billable": 1})
		story.insert()
		story.reload()
		row_name = story.custom_task_split[0].name

		generated = frappe.get_doc("Task", story.custom_task_split[0].generated_task)
		generated.custom_is_billable = 0
		generated.save()

		self.assertEqual(frappe.db.get_value("Task Split", row_name, "is_billable"), 0)

	def test_create_task_without_hours_carries_billable_for_allocate_hours_user(self):
		# A Project User with Allocate Hours but no privileged role must be able
		# to create a Task from a billable row - the flag is copied, not chosen.
		user = ensure_billable_employee_user()
		project = make_project("BC Prop Allocate Project", is_billable=1)
		project_doc = frappe.get_doc("Project", project.name)
		project_doc.append(
			"users",
			{
				"user": user,
				"custom_allocate_hours": 1,
				"custom_assign_users": 0,
				"custom_approve_extra_hours": 0,
			},
		)
		project_doc.save(ignore_permissions=True)

		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Prop Allocate Story",
				"custom_work_item_type": "Story",
				"project": project.name,
				"custom_is_billable": 1,
			}
		)
		story.append("custom_task_split", {"task_item": "Uncosted billable item", "is_billable": 1})
		story.insert()
		story.reload()
		row_name = story.custom_task_split[0].name

		frappe.set_user(user)
		try:
			task_name = create_task_without_hours(row_name)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Task", task_name, "custom_is_billable"), 1)
