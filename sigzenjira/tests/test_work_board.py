import json

import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.sigzenjira.page.work_board.work_board import (
	card_field_options,
	get_bootstrap,
	get_department_board,
	get_project_board,
	save_card_fields,
	set_task_status,
)

from .test_status_cascade import make_task_under_story
from sigzenjira.tests import ensure_test_employment_type

MEMBER_USER = "work_board_member@example.com"
IDLE_USER = "work_board_idle@example.com"
OUTSIDER_USER = "work_board_outsider@example.com"

# Project/Department/Employee fixtures are built by hand below instead of being
# declared as test dependencies: Frappe's auto dependency walk recurses into
# Company/Fiscal Year and collides with real data on mysite.in (see CLAUDE.md),
# and IGNORE_TEST_RECORD_DEPENDENCIES only works inside a doctype folder.


def ensure_user(email, first_name, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
	return email


def make_project(name, users):
	if frappe.db.exists("Project", {"project_name": name}):
		return frappe.get_doc("Project", frappe.db.get_value("Project", {"project_name": name}))
	return frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": name,
			"status": "Open",
			# Mandatory on this bench (pulse_sigzen), so a fresh Project can't be
			# inserted without it - the value itself is immaterial to the board.
			"project_type": "Internal",
			"users": [{"user": user} for user in users],
		}
	).insert(ignore_permissions=True)


def make_task(
	subject, work_item_type, project, parent_task=None, status="Open", assignees=None, expected_time=0
):
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_task_work_item_type": work_item_type,
			"project": project,
			"parent_task": parent_task,
			"status": status,
			"expected_time": expected_time,
		}
	).insert()
	if assignees:
		# Written straight to _assign: the board only ever reads this field, and
		# going through assign_to.add would drag in the ToDo assign-permission
		# gate (events/todo.py), which is not what these tests cover.
		frappe.db.set_value("Task", doc.name, "_assign", json.dumps(assignees), update_modified=False)
	return doc


def make_task_under(story, subject, status="Open", assignees=None):
	# Builds the Task through the Story's Task Split grid, which is where a
	# Story's Tasks normally come from - make_task above would leave the row to
	# be mirrored in afterwards instead. Layers assignee-writing on
	# top of that module's make_task_under_story. expected_hours=1 is
	# arbitrary but required - generate_tasks_from_split skips a row with no
	# hours, so an ungenerated row would leave `task` unresolved below.
	task = make_task_under_story(story, subject, expected_hours=1, status=status)
	if assignees:
		frappe.db.set_value("Task", task.name, "_assign", json.dumps(assignees), update_modified=False)
	return task


class TestWorkBoard(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.member = ensure_user(MEMBER_USER, "WB Member", ["Projects User", "Employee"])
		cls.idle = ensure_user(IDLE_USER, "WB Idle", ["Projects User", "Employee"])
		cls.outsider = ensure_user(OUTSIDER_USER, "WB Outsider", ["Projects User"])

		cls.project = make_project("WB Board Project", [cls.member, cls.idle])
		cls.other_project = make_project("WB Other Project", [cls.outsider])

		# Story hours are a ceiling for the rows added below
		# (rollup_story_expected_time), so declare them up front.
		cls.epic = make_task("WB Epic", "Epic", cls.project.name, expected_time=100)
		cls.story_a = make_task(
			"WB Story A", "Story", cls.project.name, cls.epic.name, expected_time=20
		)
		cls.story_b = make_task(
			"WB Story B", "Story", cls.project.name, cls.epic.name, expected_time=20
		)
		cls.task_a1 = make_task_under(cls.story_a, "WB Task A1", assignees=[cls.member])
		cls.task_a2 = make_task_under(cls.story_a, "WB Task A2")
		cls.task_b1 = make_task_under(cls.story_b, "WB Task B1", assignees=[cls.member])
		cls.sub_task = make_task("WB Sub-task", "Sub-task", cls.project.name, cls.task_a1.name)

		cls.other_epic = make_task("WB Other Epic", "Epic", cls.other_project.name)

	def tearDown(self):
		frappe.set_user("Administrator")

	def set_task(self, task, **values):
		# The fixtures are built once per class and db.set_value survives between
		# tests, so every write has to put back what it found or it leaks into
		# whichever test happens to run next.
		before = {field: frappe.db.get_value("Task", task, field) for field in values}
		frappe.db.set_value("Task", task, values)
		self.addCleanup(frappe.db.set_value, "Task", task, before)

	def test_board_returns_every_open_task_in_the_project(self):
		board = get_project_board(self.project.name)
		subjects = sorted(t["subject"] for t in board["tasks"])
		# Task level only - Epics, Stories and Sub-tasks are never cards.
		self.assertEqual(subjects, sorted([self.task_a1.subject, self.task_a2.subject, self.task_b1.subject]))

	def test_closed_tasks_are_never_cards(self):
		for status in ("Completed", "Cancelled"):
			with self.subTest(status=status):
				self.set_task(self.task_a2.name, status=status)
				board = get_project_board(self.project.name)
				self.assertNotIn(self.task_a2.name, [t["name"] for t in board["tasks"]])

	def test_rows_list_the_projects_open_epics_and_stories(self):
		board = get_project_board(self.project.name)
		self.assertEqual([e["name"] for e in board["epics"]], [self.epic.name])
		self.assertEqual(
			[s["name"] for s in board["stories"]], [self.story_a.name, self.story_b.name]
		)
		# Every chip carries the status it renders.
		self.assertTrue(all(row["status"] for row in board["epics"] + board["stories"]))

	def test_closed_work_items_leave_the_rows(self):
		# The rows are "what is still on the line" - same rule as the cards.
		for item, key in ((self.epic.name, "epics"), (self.story_b.name, "stories")):
			for status in ("Completed", "Cancelled"):
				with self.subTest(item=item, status=status):
					self.set_task(item, status=status)
					names = [row["name"] for row in get_project_board(self.project.name)[key]]
					self.assertNotIn(item, names)

	def test_story_row_names_the_epic_it_hangs_off(self):
		# The client groups the Story row by this, so an Epic selection can narrow it.
		stories = get_project_board(self.project.name)["stories"]
		self.assertEqual({s["epic"] for s in stories}, {self.epic.name})

	def test_selected_stories_narrow_the_cards(self):
		board = get_project_board(self.project.name, stories=json.dumps([self.story_a.name]))
		self.assertEqual(
			sorted(t["subject"] for t in board["tasks"]),
			sorted([self.task_a1.subject, self.task_a2.subject]),
		)
		# The rows themselves stay whole - the selection filters below it, not itself.
		self.assertEqual(len(board["stories"]), 2)

	def test_an_empty_selection_empties_the_kanban(self):
		# What a picked Epic with no open Story under it resolves to. Not the same as
		# no selection at all, which shows the whole project.
		self.assertEqual(get_project_board(self.project.name, stories=json.dumps([]))["tasks"], [])
		self.assertEqual(len(get_project_board(self.project.name)["tasks"]), 3)

	def test_a_selection_ignores_the_date_range(self):
		today = frappe.utils.today()
		self.set_task(self.task_a1.name, exp_end_date=frappe.utils.add_days(today, 400))
		board = get_project_board(
			self.project.name,
			stories=json.dumps([self.story_a.name]),
			from_date=frappe.utils.get_first_day(today),
			to_date=frappe.utils.get_last_day(today),
		)
		self.assertIn(self.task_a1.name, [t["name"] for t in board["tasks"]])

	def test_range_keeps_tasks_inside_it_and_every_undated_task(self):
		today = frappe.utils.today()
		# Mid-afternoon on purpose: exp_end_date is a Datetime, so the bounds have to
		# cover the whole of the From and To days, not just midnight.
		self.set_task(self.task_a1.name, exp_end_date=f"{today} 15:30:00")
		self.set_task(self.task_a2.name, exp_end_date=frappe.utils.add_days(today, 40))
		# task_b1 keeps a null ECD - undated work is still work, so the range
		# bounds the fetch without hiding it (_ecd_range_conditions).
		board = get_project_board(
			self.project.name,
			from_date=frappe.utils.get_first_day(today),
			to_date=frappe.utils.get_last_day(today),
		)
		self.assertEqual(
			sorted(t["name"] for t in board["tasks"]),
			sorted([self.task_a1.name, self.task_b1.name]),
		)

	def test_open_ended_range_uses_the_bound_it_was_given(self):
		today = frappe.utils.today()
		self.set_task(self.task_a1.name, exp_end_date=frappe.utils.add_days(today, -5))
		self.set_task(self.task_a2.name, exp_end_date=frappe.utils.add_days(today, 5))

		# task_b1 has no ECD and rides along with either open-ended bound.
		self.assertEqual(
			sorted(t["name"] for t in get_project_board(self.project.name, from_date=today)["tasks"]),
			sorted([self.task_a2.name, self.task_b1.name]),
		)
		self.assertEqual(
			sorted(t["name"] for t in get_project_board(self.project.name, to_date=today)["tasks"]),
			sorted([self.task_a1.name, self.task_b1.name]),
		)

	def test_sub_tasks_are_never_cards(self):
		# cascade_completion_to_parent already rolls a Sub-task into its Task.
		names = [t["name"] for t in get_project_board(self.project.name)["tasks"]]
		self.assertNotIn(self.sub_task.name, names)

	def test_members_include_project_user_with_no_tasks(self):
		board = get_project_board(self.project.name)
		users = [m["user"] for m in board["members"]]
		self.assertIn(self.idle, users)
		self.assertIn(self.member, users)

	def test_assignees_resolved_on_cards(self):
		board = get_project_board(self.project.name)
		card = next(t for t in board["tasks"] if t["name"] == self.task_a1.name)
		self.assertEqual([a["user"] for a in card["assignees"]], [self.member])

	def test_cards_name_the_story_they_belong_to(self):
		cards = get_project_board(self.project.name)["tasks"]
		by_story = {}
		for card in cards:
			by_story.setdefault(card["parent_task"], []).append(card["subject"])
		self.assertEqual(
			{story: sorted(subjects) for story, subjects in by_story.items()},
			{
				self.story_a.name: sorted([self.task_a1.subject, self.task_a2.subject]),
				self.story_b.name: [self.task_b1.subject],
			},
		)

	def test_extra_fields_land_on_the_card(self):
		board = get_project_board(self.project.name, extra_fields=json.dumps(["expected_time"]))
		self.assertEqual(board["extra_fields"], ["expected_time"])
		self.assertIn("expected_time", board["tasks"][0]["extra"])

	def test_unknown_extra_field_is_dropped_not_queried(self):
		board = get_project_board(
			self.project.name,
			extra_fields=json.dumps(["expected_time", "modified_by", "(select 1)"]),
		)
		# modified_by is not a docfield and the third entry is a SQL-shaped
		# string: both must be filtered out before they reach the SELECT.
		self.assertEqual(board["extra_fields"], ["expected_time"])

	def test_card_field_options_exclude_base_and_no_value_fields(self):
		options = {opt["fieldname"] for opt in card_field_options()}
		self.assertIn("expected_time", options)
		self.assertNotIn("subject", options)
		self.assertNotIn("status", options)

	def test_card_fields_reach_the_database_not_just_the_cache(self):
		from frappe.model.utils.user_settings import get_user_settings

		frappe.set_user(self.member)
		save_card_fields(json.dumps(["expected_time", "modified_by"]))
		# Dropping the cache is what a bench restart does. Before save_card_fields
		# existed the client wrote redis only, so the pick died here.
		frappe.cache.delete_key("_user_settings")
		settings = json.loads(get_user_settings("Task"))
		self.assertEqual(settings["work_board_card_fields"], ["expected_time"])

	def test_another_projects_story_cannot_pull_its_tasks_in(self):
		# The project filter is what keeps a hand-crafted selection honest.
		board = get_project_board(self.project.name, stories=json.dumps([self.other_epic.name]))
		self.assertEqual(board["tasks"], [])

	def test_non_member_cannot_open_a_project_board(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			get_project_board(self.project.name)

	def test_member_sees_whole_project_not_just_own_tasks(self):
		frappe.set_user(self.idle)
		board = get_project_board(self.project.name)
		# `idle` has no assignment at all - project-scoped visibility, not
		# own-tasks-only, so the full task set still comes back.
		self.assertEqual(len(board["tasks"]), 3)

	def test_bootstrap_lists_only_projects_the_user_is_a_member_of(self):
		frappe.set_user(self.outsider)
		names = [p["name"] for p in get_bootstrap()["projects"]]
		self.assertIn(self.other_project.name, names)
		self.assertNotIn(self.project.name, names)

	def test_dropping_a_card_writes_the_columns_status(self):
		self.set_task(self.task_a2.name, status="Open")
		for column, status in (("In Progress", "Working"), ("In Review", "Pending Review"), ("To Do", "Open")):
			with self.subTest(column=column):
				self.assertEqual(set_task_status(self.task_a2.name, column), status)
				self.assertEqual(frappe.db.get_value("Task", self.task_a2.name, "status"), status)

	def test_an_unknown_column_is_refused(self):
		# The column name is client-supplied, so it must never reach doc.status raw.
		self.set_task(self.task_a2.name, status="Open")
		with self.assertRaises(frappe.ValidationError):
			set_task_status(self.task_a2.name, "Completed")
		self.assertEqual(frappe.db.get_value("Task", self.task_a2.name, "status"), "Open")

	def test_a_non_member_cannot_move_a_card(self):
		# Reading the board is already blocked for an outsider; the write is a
		# separate endpoint and needs its own gate, not the read one.
		self.set_task(self.task_a2.name, status="Open")
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			set_task_status(self.task_a2.name, "In Progress")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Task", self.task_a2.name, "status"), "Open")


class TestWorkBoardDepartmentView(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.user = ensure_user(MEMBER_USER, "WB Member", ["Projects User", "Employee"])
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company")

		cls.department = frappe.db.get_value("Department", {"department_name": "WB Test Department"})
		if not cls.department:
			cls.department = (
				frappe.get_doc(
					{
						"doctype": "Department",
						"department_name": "WB Test Department",
						"company": cls.company,
						"is_group": 0,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)

		if not frappe.db.exists("Employee", {"user_id": cls.user}):
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "WB Member",
					"company": cls.company,
					"status": "Active",
					"gender": "Female",
					"date_of_birth": "1995-01-01",
					"date_of_joining": "2024-01-01",
					"employment_type": ensure_test_employment_type(),
					"department": cls.department,
					"user_id": cls.user,
				}
			).insert(ignore_permissions=True)
		else:
			frappe.db.set_value(
				"Employee",
				frappe.db.get_value("Employee", {"user_id": cls.user}),
				"department",
				cls.department,
			)

		cls.project = make_project("WB Dept Project", [cls.user])
		cls.epic = make_task("WB Dept Epic", "Epic", cls.project.name, expected_time=100)
		cls.story = make_task(
			"WB Dept Story", "Story", cls.project.name, cls.epic.name, expected_time=20
		)
		cls.open_task = make_task_under(cls.story, "WB Dept Open", assignees=[cls.user])
		cls.done_task = make_task_under(cls.story, "WB Dept Done", status="Completed", assignees=[cls.user])

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_department_board_maps_employee_to_assignee(self):
		board = get_department_board(self.department)
		self.assertIn(self.user, [m["user"] for m in board["members"]])
		names = [t["name"] for t in board["tasks"]]
		self.assertIn(self.open_task.name, names)

	def test_department_board_excludes_completed_work(self):
		board = get_department_board(self.department)
		self.assertNotIn(self.done_task.name, [t["name"] for t in board["tasks"]])

	def test_department_cards_carry_project_name(self):
		board = get_department_board(self.department)
		card = next(t for t in board["tasks"] if t["name"] == self.open_task.name)
		self.assertEqual(card["project"], self.project.name)
		self.assertEqual(card["project_name"], "WB Dept Project")
