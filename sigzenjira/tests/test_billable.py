import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from sigzenjira.events.billable import BILLABLE_FIELDS
from sigzenjira.events.issue import make_story
from sigzenjira.events.task import create_task_without_hours
from sigzenjira.tests import ensure_test_employment_type

# No IGNORE_TEST_RECORD_DEPENDENCIES here: it only works for test modules inside
# a doctype folder (frappe/tests/classes/integration_test_case.py:59 raises
# NotImplementedError otherwise - see test_work_board.py for the same note).
# It is not needed either. This module does create Project/Issue/Employee/
# Timesheet documents, but every one of them is a minimal fixture built by hand
# in the helpers below and rolled back with the test - so frappe's automatic
# dependency walk (which would recurse into Company/Fiscal Year and collide with
# the real data on mysite.in) is never invoked.


def make_project(name, is_billable=0):
	# project_type is mandatory on this bench (a Property Setter, not app code),
	# so every Project fixture here has to carry one.
	return frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": name,
			"project_type": "Internal",
			"custom_project_is_billable": is_billable,
		}
	).insert(ignore_permissions=True)


def make_issue(subject, project=None, is_billable=0):
	return frappe.get_doc(
		{"doctype": "Issue", "subject": subject, "project": project, "custom_issue_is_billable": is_billable}
	).insert()


def make_task(
	subject, work_item_type, parent_task=None, project=None, expected_time=0, is_billable=0, issue=None
):
	return frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_task_work_item_type": work_item_type,
			"parent_task": parent_task,
			"project": project,
			"issue": issue,
			"expected_time": expected_time,
			"custom_task_is_billable": is_billable,
		}
	).insert()


class TestBillableFields(IntegrationTestCase):
	def test_billable_custom_fields_exist(self):
		# Asserted straight off BILLABLE_FIELDS so the map the clamp actually
		# resolves through is the thing under test - a doctype added there
		# without its custom field fails here rather than at runtime.
		for doctype, fieldname in BILLABLE_FIELDS.items():
			self.assertTrue(
				frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": fieldname}),
				f"{fieldname} missing on {doctype}",
			)

	def test_billable_fields_are_checks_defaulting_to_zero(self):
		for doctype, fieldname in BILLABLE_FIELDS.items():
			meta_field = frappe.get_meta(doctype).get_field(fieldname)
			self.assertEqual(meta_field.fieldtype, "Check")
			self.assertEqual(meta_field.default, "0")

	def test_additional_hours_request_shows_its_tasks_billable_flag(self):
		# Read-only mirror for the approver - granting hours on billable work
		# costs the customer money, so the flag has to be visible at approval
		# time. fetch_from does the work; nothing here may write back.
		meta_field = frappe.get_meta("Additional Hours Request").get_field("is_billable")
		self.assertEqual(meta_field.fetch_from, "task.custom_task_is_billable")
		self.assertEqual(meta_field.read_only, 1)

		task = make_task("AHR billable mirror", "Task", project=make_project("AHR Billable Co", 1).name)
		task.db_set("custom_task_is_billable", 1)
		request = frappe.get_doc(
			{
				"doctype": "Additional Hours Request",
				"task": task.name,
				"additional_hours_requested": 2,
				"reason": "Scope grew",
			}
		).insert()
		self.assertEqual(request.is_billable, 1)

	def test_task_split_has_is_billable_column(self):
		meta_field = frappe.get_meta("Task Split").get_field("is_billable")
		self.assertIsNotNone(meta_field)
		self.assertEqual(meta_field.fieldtype, "Check")
		self.assertEqual(meta_field.in_list_view, 1)


class TestBillableUpwardClamp(IntegrationTestCase):
	def test_billable_subtask_under_non_billable_task_throws(self):
		# Sub-task under Task is the plain parent/child pair - a Task/Story pair
		# would drag in create_split_row_for_manual_task's row mirroring and the
		# Story budget check, neither of which this clamp test is about.
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

		self.assertEqual(billed.custom_task_is_billable, 1)
		self.assertEqual(free.custom_task_is_billable, 0)

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
				"custom_task_work_item_type": "Story",
				"custom_task_is_billable": 0,
			}
		)
		story.append("custom_task_task_split", {"task_item": "Billed work", "is_billable": 1})

		with self.assertRaises(frappe.ValidationError) as caught:
			story.insert()
		self.assertIn("marked Billable", str(caught.exception))


class TestBillableDownwardClamp(IntegrationTestCase):
	def test_unchecking_task_with_billable_subtask_throws(self):
		# Sub-task under Task is the plain parent/child pair - a Task/Story pair
		# would drag in create_split_row_for_manual_task's row mirroring, which
		# this clamp test is not about.
		task = make_task("BC Down Task", "Task", expected_time=10, is_billable=1)
		make_task("BC Down Sub", "Sub-task", task.name, is_billable=1)

		task.reload()
		task.custom_task_is_billable = 0
		with self.assertRaises(frappe.ValidationError) as caught:
			task.save()
		self.assertIn("Cannot turn off Billable while", str(caught.exception))

	def test_unchecking_task_with_only_non_billable_subtasks_succeeds(self):
		task = make_task("BC Down Free Task", "Task", expected_time=10, is_billable=1)
		make_task("BC Down Free Sub", "Sub-task", task.name, is_billable=0)

		task.reload()
		task.custom_task_is_billable = 0
		task.save()

		self.assertEqual(frappe.db.get_value("Task", task.name, "custom_task_is_billable"), 0)

	def test_unchecking_project_with_billable_issue_throws(self):
		project = make_project("BC Down Project", is_billable=1)
		make_issue("BC Down Issue", project=project.name, is_billable=1)

		project.reload()
		project.custom_project_is_billable = 0
		with self.assertRaises(frappe.ValidationError) as caught:
			project.save()
		self.assertIn("Cannot turn off Billable while", str(caught.exception))

	def test_unchecking_issue_with_billable_story_throws(self):
		project = make_project("BC Down Issue Project", is_billable=1)
		issue = make_issue("BC Down Billed Issue", project=project.name, is_billable=1)
		make_task("BC Down Issue Story", "Story", project=project.name, issue=issue.name, is_billable=1)

		issue.reload()
		issue.custom_issue_is_billable = 0
		with self.assertRaises(frappe.ValidationError) as caught:
			issue.save()
		self.assertIn("Cannot turn off Billable while", str(caught.exception))

	def test_story_and_its_rows_can_be_unbilled_in_one_save(self):
		# The DB still holds is_billable=1 on the child rows while the parent's
		# validate() runs, so reading rows from the DB here would throw on a
		# save that legitimately unbills both at once.
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Down Both Story",
				"custom_task_work_item_type": "Story",
				"custom_task_is_billable": 1,
			}
		)
		story.append("custom_task_task_split", {"task_item": "Some work", "is_billable": 1})
		story.insert()

		story.reload()
		story.custom_task_is_billable = 0
		story.custom_task_task_split[0].is_billable = 0
		story.save()

		self.assertEqual(frappe.db.get_value("Task", story.name, "custom_task_is_billable"), 0)

	def test_unticking_a_split_row_with_a_billable_subtask_under_it_throws(self):
		# The split grid is the primary editing surface for a Story, and its
		# row -> Task push is a raw db.set_value that skips validate() - so
		# without validate_split_row_unbilling this would silently leave a
		# billable Sub-task hanging under a Task that just stopped being
		# billable, while the same edit made on the Task directly throws.
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Row Unbill Story",
				"custom_task_work_item_type": "Story",
				"custom_task_is_billable": 1,
			}
		)
		story.append("custom_task_task_split", {"task_item": "Row work", "expected_hours": 4, "is_billable": 1})
		story.insert()
		story.reload()

		generated = story.custom_task_task_split[0].generated_task
		sub = make_task("BC Row Unbill Sub", "Sub-task", generated, is_billable=1)

		story.custom_task_task_split[0].is_billable = 0
		with self.assertRaises(frappe.ValidationError) as caught:
			story.save()
		self.assertIn("Cannot turn off Billable on row", str(caught.exception))
		self.assertIn(sub.name, str(caught.exception))
		self.assertEqual(frappe.db.get_value("Task", generated, "custom_task_is_billable"), 1)

		sub.reload()
		sub.custom_task_is_billable = 0
		sub.save()

		story.reload()
		story.custom_task_task_split[0].is_billable = 0
		story.save()

		self.assertEqual(frappe.db.get_value("Task", generated, "custom_task_is_billable"), 0)


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
			as_employee.custom_task_is_billable = 1
			with self.assertRaises(frappe.ValidationError) as caught:
				as_employee.save()
			self.assertIn("can change Billable.", str(caught.exception))
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

		self.assertEqual(frappe.db.get_value("Task", task.name, "custom_task_is_billable"), 1)

	def test_privileged_role_can_change_billable(self):
		parent = make_task("BC Perm Privileged Parent", "Task", expected_time=10, is_billable=1)
		task = make_task("BC Perm Privileged Sub", "Sub-task", parent.name, is_billable=0)

		task.custom_task_is_billable = 1
		task.save()

		self.assertEqual(frappe.db.get_value("Task", task.name, "custom_task_is_billable"), 1)

	def test_non_privileged_user_cannot_change_split_row_billable(self):
		user = ensure_billable_employee_user()
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Perm Split Story",
				"custom_task_work_item_type": "Story",
				"custom_task_is_billable": 1,
			}
		)
		story.append("custom_task_task_split", {"task_item": "Perm item", "is_billable": 0})
		story.insert()

		frappe.set_user(user)
		try:
			as_employee = frappe.get_doc("Task", story.name)
			as_employee.custom_task_task_split[0].is_billable = 1
			with self.assertRaises(frappe.ValidationError) as caught:
				as_employee.save()
			# Discriminating substring on purpose: a bare "Task Split" also matches
			# validate_task_split_expected_hours_permission's message, which runs
			# earlier in the same validate chain.
			self.assertIn("change Billable on the Task Split table", str(caught.exception))
		finally:
			frappe.set_user("Administrator")

	def test_allocate_hour_flag_holder_can_change_split_row_billable(self):
		# The "Allocate Hour + Billable Check/Uncheck" grant. Same shape as the
		# denial above, only the Story now sits on a Project the user is flagged
		# on - so the flag is the sole difference between saving and throwing.
		user = ensure_billable_employee_user()
		project = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": "BC Perm Split Grant Project",
				"project_type": "Internal",
				"custom_project_is_billable": 1,
				# Every Check spelled out: one left off a dict comes back 1, not 0.
				"users": [
					{
						"user": user,
						"custom_project_user_allocate_hours": 1,
						"custom_project_user_assign_users": 0,
						"custom_project_user_approve_extra_hours": 0,
						"custom_project_user_set_work_item_type": 0,
					}
				],
			}
		).insert(ignore_permissions=True)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Perm Split Grant Story",
				"custom_task_work_item_type": "Story",
				"project": project.name,
				"custom_task_is_billable": 1,
			}
		)
		story.append("custom_task_task_split", {"task_item": "Grant item", "is_billable": 0})
		story.insert()
		row_name = story.custom_task_task_split[0].name

		frappe.set_user(user)
		try:
			as_employee = frappe.get_doc("Task", story.name)
			as_employee.custom_task_task_split[0].is_billable = 1
			as_employee.save()

			# The grant stops at the grid: the Story's own flag stays out of reach.
			# Not asserted on message - a flag holder without Set Work Item Type
			# trips validate_story_template_only ("You can only select a Task
			# Template on this Story.") before the Billable gate even runs.
			as_employee.custom_task_is_billable = 0
			with self.assertRaises(frappe.ValidationError):
				as_employee.save()
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Task Split", row_name, "is_billable"), 1)
		self.assertEqual(frappe.db.get_value("Task", story.name, "custom_task_is_billable"), 1)

	def test_non_privileged_user_cannot_add_a_billable_split_row(self):
		# Adding a row is a distinct path from flipping one: the new row has no
		# pre-save snapshot, so it lands on before_rows' default-to-0 branch.
		user = ensure_billable_employee_user()
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Perm Split Add Story",
				"custom_task_work_item_type": "Story",
				"custom_task_is_billable": 1,
			}
		).insert()

		frappe.set_user(user)
		try:
			as_employee = frappe.get_doc("Task", story.name)
			as_employee.append("custom_task_task_split", {"task_item": "Added item", "is_billable": 1})
			with self.assertRaises(frappe.ValidationError) as caught:
				as_employee.save()
			self.assertIn("change Billable on the Task Split table", str(caught.exception))
		finally:
			frappe.set_user("Administrator")

	def test_employee_can_create_a_billable_subtask_under_a_billable_task(self):
		# The seeded-from-parent case. It used to throw, which pushed an Employee
		# toward unticking Billable - silent under-billing on the one thing they
		# are allowed to create.
		user = ensure_billable_employee_user()
		parent = make_task("BC New Gate Parent", "Task", expected_time=10, is_billable=1)

		frappe.set_user(user)
		try:
			sub = frappe.get_doc(
				{
					"doctype": "Task",
					"subject": "BC New Gate Sub",
					"custom_task_work_item_type": "Sub-task",
					"parent_task": parent.name,
					"custom_task_is_billable": 1,
				}
			).insert()
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Task", sub.name, "custom_task_is_billable"), 1)

	def test_employee_still_cannot_invent_billable_without_a_source(self):
		# Project, not a parentless Sub-task: PARENT_SOURCES["Project"] is empty,
		# so a Project genuinely has nothing to inherit from. A Sub-task with no
		# parent_task would trip validate_hierarchy ("A Sub-task must have a parent
		# task of type Task.") earlier in the chain and never reach the gate.
		user = ensure_billable_employee_user()

		frappe.set_user(user)
		try:
			orphan = frappe.get_doc(
				{
					"doctype": "Project",
					# project_type is mandatory on this bench (a Property Setter, not app code).
					"project_type": "Internal",
					"project_name": "BC New Gate Orphan Project",
					"custom_project_is_billable": 1,
				}
			)
			with self.assertRaises(frappe.ValidationError) as caught:
				orphan.insert()
			self.assertIn("can change Billable.", str(caught.exception))
		finally:
			frappe.set_user("Administrator")


class TestBillablePropagation(IntegrationTestCase):
	def test_make_story_copies_billable_issue(self):
		project = make_project("BC Prop Billed Project", is_billable=1)
		issue = make_issue("BC Prop Billed Issue", project=project.name, is_billable=1)

		story = frappe.get_doc("Task", make_story(issue.name))

		self.assertEqual(story.custom_task_is_billable, 1)

	def test_make_story_copies_unbilled_support_issue(self):
		# Post-delivery support: Project still billable, this Issue is not.
		project = make_project("BC Prop Support Project", is_billable=1)
		issue = make_issue("BC Prop Support Issue", project=project.name, is_billable=0)

		story = frappe.get_doc("Task", make_story(issue.name))

		self.assertEqual(story.custom_task_is_billable, 0)

	def test_split_row_generates_billable_task(self):
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Prop Split Story",
				"custom_task_work_item_type": "Story",
				"custom_task_is_billable": 1,
			}
		)
		story.append("custom_task_task_split", {"task_item": "Billed item", "expected_hours": 3, "is_billable": 1})
		story.append("custom_task_task_split", {"task_item": "Free item", "expected_hours": 2, "is_billable": 0})
		story.insert()

		story.reload()
		billed_row, free_row = story.custom_task_task_split[0], story.custom_task_task_split[1]

		self.assertEqual(frappe.db.get_value("Task", billed_row.generated_task, "custom_task_is_billable"), 1)
		self.assertEqual(frappe.db.get_value("Task", free_row.generated_task, "custom_task_is_billable"), 0)

	def test_unchecking_split_row_pushes_to_generated_task(self):
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Prop Push Story",
				"custom_task_work_item_type": "Story",
				"custom_task_is_billable": 1,
			}
		)
		story.append("custom_task_task_split", {"task_item": "Push item", "expected_hours": 3, "is_billable": 1})
		story.insert()
		story.reload()
		generated = story.custom_task_task_split[0].generated_task
		# Generation seeded it from the row; without this the post-assert below
		# could not tell a working push from a field that was never set.
		self.assertEqual(frappe.db.get_value("Task", generated, "custom_task_is_billable"), 1)

		story.custom_task_task_split[0].is_billable = 0
		story.save()

		self.assertEqual(frappe.db.get_value("Task", generated, "custom_task_is_billable"), 0)

	def test_unchecking_generated_task_pulls_back_to_split_row(self):
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Prop Pull Story",
				"custom_task_work_item_type": "Story",
				"custom_task_is_billable": 1,
			}
		)
		story.append("custom_task_task_split", {"task_item": "Pull item", "expected_hours": 3, "is_billable": 1})
		story.insert()
		story.reload()
		row_name = story.custom_task_task_split[0].name
		# Generation seeded it from the row; without this the post-assert below
		# could not tell a working pull from a field that was never set.
		self.assertEqual(frappe.db.get_value("Task Split", row_name, "is_billable"), 1)

		generated = frappe.get_doc("Task", story.custom_task_task_split[0].generated_task)
		generated.custom_task_is_billable = 0
		generated.save()

		self.assertEqual(frappe.db.get_value("Task Split", row_name, "is_billable"), 0)

	def test_create_task_without_hours_carries_the_rows_billable_flag(self):
		# Nothing else in the app calls this function, so without a direct test
		# its dict key and get_value field-list entry are unverified. Run as
		# Administrator: user_has_project_flag returns True unconditionally for
		# it, so both the Allocate Hours gate and the work-item-type gate clear.
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "BC Prop Uncosted Story",
				"custom_task_work_item_type": "Story",
				"custom_task_is_billable": 1,
			}
		)
		story.append("custom_task_task_split", {"task_item": "Billed uncosted", "is_billable": 1})
		story.append("custom_task_task_split", {"task_item": "Free uncosted", "is_billable": 0})
		story.insert()
		story.reload()

		# Assert right after each call, before the next one - core ERPNext's
		# Task.on_update -> populate_depends_on() does a real parent.save() on
		# every child Task insert (see generate_tasks_from_split's own comment
		# on this same re-entrancy). That re-triggers the Story's on_update
		# chain, including sync_split_row_edits_to_generated_task, which by the
		# second call would find the first row's generated_task already set
		# and push its billable flag independently - masking a broken
		# create_task_without_hours behind the OTHER sync path. Checking
		# billed_task before free_task exists keeps this test isolated to the
		# function under test.
		billed_task = create_task_without_hours(story.custom_task_task_split[0].name)
		self.assertEqual(frappe.db.get_value("Task", billed_task, "custom_task_is_billable"), 1)

		free_task = create_task_without_hours(story.custom_task_task_split[1].name)
		self.assertEqual(frappe.db.get_value("Task", free_task, "custom_task_is_billable"), 0)


def make_billable_test_employee():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "BC Timesheet Tester",
			"company": company,
			"status": "Active",
			"gender": "Male",
			"date_of_birth": "1995-01-01",
			"date_of_joining": "2024-01-01",
			"employment_type": ensure_test_employment_type(),
		}
	).insert()


class TestBillableTimesheetLock(IntegrationTestCase):
	def test_row_against_non_billable_task_is_forced_off(self):
		employee = make_billable_test_employee()
		task = make_task("BC TS Free Task", "Task", expected_time=5, is_billable=0)

		timesheet = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"employee": employee.name,
				"time_logs": [
					{
						"activity_type": "Execution",
						"task": task.name,
						"from_time": f"{today()} 09:00:00",
						"hours": 2,
						"is_billable": 1,
					}
				],
			}
		).insert()

		self.assertEqual(timesheet.time_logs[0].is_billable, 0)

	def test_row_against_billable_task_is_forced_on(self):
		employee = make_billable_test_employee()
		task = make_task("BC TS Billed Task", "Task", expected_time=5, is_billable=1)

		timesheet = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"employee": employee.name,
				"time_logs": [
					{
						"activity_type": "Execution",
						"task": task.name,
						"from_time": f"{today()} 09:00:00",
						"hours": 2,
						"is_billable": 0,
					}
				],
			}
		).insert()

		self.assertEqual(timesheet.time_logs[0].is_billable, 1)

	def test_row_without_task_keeps_its_manual_flag(self):
		employee = make_billable_test_employee()

		timesheet = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"employee": employee.name,
				"time_logs": [
					{
						"activity_type": "Execution",
						"from_time": f"{today()} 09:00:00",
						"hours": 2,
						"is_billable": 1,
					}
				],
			}
		).insert()

		self.assertEqual(timesheet.time_logs[0].is_billable, 1)

	def test_timesheet_detail_is_billable_is_read_only_when_task_set(self):
		meta_field = frappe.get_meta("Timesheet Detail").get_field("is_billable")
		self.assertEqual(meta_field.read_only_depends_on, "eval:doc.task")


class TestBillableHoursSplit(IntegrationTestCase):
	def make_timesheet(self, employee, task, hours, billing_hours=None, project=None, submit=False):
		row = {
			"activity_type": "Execution",
			"task": task,
			"project": project,
			"from_time": f"{today()} 09:00:00",
			"hours": hours,
		}
		if billing_hours is not None:
			row["billing_hours"] = billing_hours

		timesheet = frappe.get_doc(
			{"doctype": "Timesheet", "employee": employee, "time_logs": [row]}
		).insert()
		if submit:
			timesheet.submit()
		return timesheet

	def test_billable_row_defaults_to_billing_every_hour_worked(self):
		employee = make_billable_test_employee()
		project = make_project("BC Split Full", is_billable=1)
		task = make_task("BC Split Full Task", "Task", project=project.name, is_billable=1)

		timesheet = self.make_timesheet(employee.name, task.name, hours=4)
		row = timesheet.time_logs[0]

		self.assertEqual(row.billing_hours, 4)
		self.assertEqual(row.custom_timesheet_detail_non_billable_hours, 0)

	def test_one_row_can_hold_both_billable_and_non_billable_hours(self):
		# The case the whole split exists for: a billable Task where only part of
		# the time logged against it is actually billed.
		employee = make_billable_test_employee()
		project = make_project("BC Split Partial", is_billable=1)
		task = make_task("BC Split Partial Task", "Task", project=project.name, is_billable=1)

		timesheet = self.make_timesheet(employee.name, task.name, hours=5, billing_hours=3)
		row = timesheet.time_logs[0]

		self.assertEqual(row.billing_hours, 3)
		self.assertEqual(row.custom_timesheet_detail_non_billable_hours, 2)

	def test_non_billable_task_puts_every_hour_in_non_billable(self):
		employee = make_billable_test_employee()
		project = make_project("BC Split Free", is_billable=0)
		task = make_task("BC Split Free Task", "Task", project=project.name, is_billable=0)

		timesheet = self.make_timesheet(employee.name, task.name, hours=6, billing_hours=6)
		row = timesheet.time_logs[0]

		# billing_hours was asked for on a non-billable task and core zeroed it
		# (timesheet_detail.py:update_billing_hours), so the whole 6 is unbilled.
		self.assertEqual(row.is_billable, 0)
		self.assertEqual(row.billing_hours, 0)
		self.assertEqual(row.custom_timesheet_detail_non_billable_hours, 6)


class TestProjectBillableRollup(IntegrationTestCase):
	def test_submitting_a_timesheet_rolls_hours_up_to_the_project(self):
		employee = make_billable_test_employee()
		project = make_project("BC Rollup Split", is_billable=1)
		task = make_task("BC Rollup Split Task", "Task", project=project.name, is_billable=1)

		TestBillableHoursSplit.make_timesheet(
			self, employee.name, task.name, hours=5, billing_hours=3, project=project.name, submit=True
		)

		self.assertEqual(frappe.db.get_value("Project", project.name, "custom_project_billable_hours"), 3)
		self.assertEqual(
			frappe.db.get_value("Project", project.name, "custom_project_non_billable_hours"), 2
		)

	def test_project_total_does_not_double_count_a_subtask_under_a_task(self):
		# The reason recompute_project_billable_hours sums Timesheet Detail rows
		# instead of Tasks: the parent Task's own custom_task_billable_hours
		# already contains the Sub-task's, so adding Tasks up would count the
		# same hour twice.
		employee = make_billable_test_employee()
		project = make_project("BC Rollup Nested", is_billable=1)
		parent = make_task("BC Rollup Parent", "Task", project=project.name, is_billable=1)
		child = make_task(
			"BC Rollup Child", "Sub-task", parent_task=parent.name, project=project.name, is_billable=1
		)

		TestBillableHoursSplit.make_timesheet(
			self, employee.name, child.name, hours=4, project=project.name, submit=True
		)

		self.assertEqual(frappe.db.get_value("Task", parent.name, "custom_task_billable_hours"), 4)
		self.assertEqual(frappe.db.get_value("Project", project.name, "custom_project_billable_hours"), 4)

	def test_cancelling_a_timesheet_takes_the_hours_back_off_the_project(self):
		employee = make_billable_test_employee()
		project = make_project("BC Rollup Cancel", is_billable=1)
		task = make_task("BC Rollup Cancel Task", "Task", project=project.name, is_billable=1)

		timesheet = TestBillableHoursSplit.make_timesheet(
			self, employee.name, task.name, hours=5, billing_hours=3, project=project.name, submit=True
		)
		timesheet.cancel()

		self.assertEqual(frappe.db.get_value("Project", project.name, "custom_project_billable_hours"), 0)
		self.assertEqual(
			frappe.db.get_value("Project", project.name, "custom_project_non_billable_hours"), 0
		)
