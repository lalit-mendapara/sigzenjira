import json

import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.sigzenjira.work_board import (
	card_field_options,
	get_bootstrap,
	get_department_board,
	get_project_board,
	save_card_fields,
	search_work_items,
)

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
			"users": [{"user": user} for user in users],
		}
	).insert(ignore_permissions=True)


def make_task(subject, work_item_type, project, parent_task=None, status="Open", assignees=None):
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_work_item_type": work_item_type,
			"project": project,
			"parent_task": parent_task,
			"status": status,
		}
	).insert()
	if assignees:
		# Written straight to _assign: the board only ever reads this field, and
		# going through assign_to.add would drag in the ToDo assign-permission
		# gate (custom/todo.py), which is not what these tests cover.
		frappe.db.set_value("Task", doc.name, "_assign", json.dumps(assignees), update_modified=False)
	return doc


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

		cls.epic = make_task("WB Epic", "Epic", cls.project.name)
		cls.story_a = make_task("WB Story A", "Story", cls.project.name, cls.epic.name)
		cls.story_b = make_task("WB Story B", "Story", cls.project.name, cls.epic.name)
		cls.task_a1 = make_task(
			"WB Task A1", "Task", cls.project.name, cls.story_a.name, assignees=[cls.member]
		)
		cls.task_a2 = make_task("WB Task A2", "Task", cls.project.name, cls.story_a.name)
		cls.task_b1 = make_task(
			"WB Task B1", "Task", cls.project.name, cls.story_b.name, assignees=[cls.member]
		)
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

	def test_no_item_and_no_range_returns_every_task_in_the_project(self):
		board = get_project_board(self.project.name)
		subjects = sorted(t["subject"] for t in board["tasks"])
		# Task level only - Epics, Stories and Sub-tasks are never cards.
		self.assertEqual(subjects, ["WB Task A1", "WB Task A2", "WB Task B1"])
		self.assertEqual(board["context"], [])

	def test_closed_tasks_are_never_cards(self):
		for status in ("Completed", "Cancelled"):
			with self.subTest(status=status):
				self.set_task(self.task_a2.name, status=status)
				for board in (
					get_project_board(self.project.name),
					get_project_board(self.project.name, self.epic.name),
					get_project_board(self.project.name, self.story_a.name),
					get_project_board(self.project.name, self.task_a2.name),
				):
					self.assertNotIn(self.task_a2.name, [t["name"] for t in board["tasks"]])

	def test_range_keeps_only_tasks_with_an_ecd_inside_it(self):
		today = frappe.utils.today()
		# Mid-afternoon on purpose: exp_end_date is a Datetime, so the bounds have to
		# cover the whole of the From and To days, not just midnight.
		self.set_task(self.task_a1.name, exp_end_date=f"{today} 15:30:00")
		self.set_task(self.task_a2.name, exp_end_date=frappe.utils.add_days(today, 40))
		# task_b1 keeps a null ECD - an undated Task is never shown while the range is on.
		board = get_project_board(
			self.project.name,
			from_date=frappe.utils.get_first_day(today),
			to_date=frappe.utils.get_last_day(today),
		)
		self.assertEqual([t["name"] for t in board["tasks"]], [self.task_a1.name])

	def test_range_never_narrows_a_picked_work_item(self):
		today = frappe.utils.today()
		self.set_task(self.task_a1.name, exp_end_date=frappe.utils.add_days(today, 400))
		board = get_project_board(
			self.project.name,
			self.epic.name,
			from_date=frappe.utils.get_first_day(today),
			to_date=frappe.utils.get_last_day(today),
		)
		subjects = sorted(t["subject"] for t in board["tasks"])
		self.assertEqual(subjects, ["WB Task A1", "WB Task A2", "WB Task B1"])

	def test_open_ended_range_uses_the_bound_it_was_given(self):
		today = frappe.utils.today()
		self.set_task(self.task_a1.name, exp_end_date=frappe.utils.add_days(today, -5))
		self.set_task(self.task_a2.name, exp_end_date=frappe.utils.add_days(today, 5))
		self.assertEqual(
			[t["name"] for t in get_project_board(self.project.name, from_date=today)["tasks"]],
			[self.task_a2.name],
		)
		# task_b1 has no ECD - the open-ended bound must not sweep it in either.
		self.assertEqual(
			[t["name"] for t in get_project_board(self.project.name, to_date=today)["tasks"]],
			[self.task_a1.name],
		)

	def test_epic_returns_only_task_level_descendants(self):
		board = get_project_board(self.project.name, self.epic.name)
		subjects = sorted(t["subject"] for t in board["tasks"])
		self.assertEqual(subjects, ["WB Task A1", "WB Task A2", "WB Task B1"])

	def test_story_returns_only_its_own_tasks(self):
		board = get_project_board(self.project.name, self.story_a.name)
		subjects = sorted(t["subject"] for t in board["tasks"])
		self.assertEqual(subjects, ["WB Task A1", "WB Task A2"])

	def test_task_item_returns_itself_only(self):
		board = get_project_board(self.project.name, self.task_a1.name)
		self.assertEqual([t["name"] for t in board["tasks"]], [self.task_a1.name])

	def test_members_include_project_user_with_no_tasks(self):
		board = get_project_board(self.project.name, self.epic.name)
		users = [m["user"] for m in board["members"]]
		self.assertIn(self.idle, users)
		self.assertIn(self.member, users)

	def test_assignees_resolved_on_cards(self):
		board = get_project_board(self.project.name, self.epic.name)
		card = next(t for t in board["tasks"] if t["name"] == self.task_a1.name)
		self.assertEqual([a["user"] for a in card["assignees"]], [self.member])

	def test_story_context_carries_its_epic(self):
		context = get_project_board(self.project.name, self.story_a.name)["context"]
		self.assertEqual(
			[(c["work_item_type"], c["name"]) for c in context],
			[("Epic", self.epic.name), ("Story", self.story_a.name)],
		)
		self.assertTrue(all(c["status"] for c in context))

	def test_epic_board_carries_its_stories_with_status(self):
		self.set_task(self.story_b.name, status="Completed")
		board = get_project_board(self.project.name, self.epic.name)
		# Completed Stories keep their lane - it reports the Epic's progress, so
		# dropping the finished ones would read as if they were never planned.
		self.assertEqual(
			[(s["name"], s["status"]) for s in board["stories"]],
			[(self.story_a.name, "Open"), (self.story_b.name, "Completed")],
		)

	def test_cards_name_the_story_their_lane_groups_by(self):
		cards = get_project_board(self.project.name, self.epic.name)["tasks"]
		by_story = {}
		for card in cards:
			by_story.setdefault(card["parent_task"], []).append(card["subject"])
		self.assertEqual(
			{story: sorted(subjects) for story, subjects in by_story.items()},
			{
				self.story_a.name: ["WB Task A1", "WB Task A2"],
				self.story_b.name: ["WB Task B1"],
			},
		)

	def test_a_story_or_task_board_gets_no_stories_strip(self):
		# Already one item deep - there is nothing left to group into lanes.
		for item in (self.story_a.name, self.task_a1.name):
			with self.subTest(item=item):
				self.assertEqual(get_project_board(self.project.name, item)["stories"], [])

	def test_project_board_names_the_stories_and_epics_its_cards_sit_under(self):
		# The client pools these cards until a tile is clicked, and then needs to
		# say which Stories (and whose Epic) the filtered board is showing.
		stories = get_project_board(self.project.name)["stories"]
		self.assertEqual(
			sorted((s["name"], s["epic_subject"]) for s in stories),
			sorted([(self.story_a.name, "WB Epic"), (self.story_b.name, "WB Epic")]),
		)

	def test_story_tile_keeps_a_matched_story_with_no_open_task(self):
		# "Story Open" counted it, so the lane has to appear even empty - that
		# emptiness is the answer to "which Stories are Open".
		self.set_task(self.task_b1.name, status="Completed")
		try:
			board = get_project_board(self.project.name, stat_type="Story", stat_status="Open")
			self.assertIn(self.story_b.name, [s["name"] for s in board["stories"]])
			self.assertNotIn(self.task_b1.name, [t["name"] for t in board["tasks"]])
		finally:
			self.set_task(self.task_b1.name, status="Open")

	def test_epic_context_is_just_the_epic(self):
		context = get_project_board(self.project.name, self.epic.name)["context"]
		self.assertEqual([c["name"] for c in context], [self.epic.name])

	def test_extra_fields_land_on_the_card(self):
		board = get_project_board(
			self.project.name, self.story_a.name, extra_fields=json.dumps(["expected_time"])
		)
		self.assertEqual(board["extra_fields"], ["expected_time"])
		self.assertIn("expected_time", board["tasks"][0]["extra"])

	def test_unknown_extra_field_is_dropped_not_queried(self):
		board = get_project_board(
			self.project.name,
			self.story_a.name,
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

	def test_item_from_another_project_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			get_project_board(self.project.name, self.other_epic.name)

	def test_non_member_cannot_open_a_project_board(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			get_project_board(self.project.name, self.epic.name)

	def test_member_sees_whole_project_not_just_own_tasks(self):
		frappe.set_user(self.idle)
		board = get_project_board(self.project.name, self.epic.name)
		# `idle` has no assignment at all - project-scoped visibility, not
		# own-tasks-only, so the full task set still comes back.
		self.assertEqual(len(board["tasks"]), 3)

	def test_bootstrap_lists_only_projects_the_user_is_a_member_of(self):
		frappe.set_user(self.outsider)
		names = [p["name"] for p in get_bootstrap()["projects"]]
		self.assertIn(self.other_project.name, names)
		self.assertNotIn(self.project.name, names)

	def test_search_work_items_is_project_scoped(self):
		frappe.set_user(self.outsider)
		with self.assertRaises(frappe.PermissionError):
			search_work_items(self.project.name, "WB")

	def test_search_work_items_matches_subject(self):
		results = search_work_items(self.project.name, "Story A")
		self.assertEqual([r["name"] for r in results], [self.story_a.name])

	def test_search_spans_all_three_levels_and_excludes_sub_tasks(self):
		results = search_work_items(self.project.name, "WB")
		types = {r["work_item_type"] for r in results}
		self.assertEqual(types, {"Epic", "Story", "Task"})
		self.assertNotIn(self.sub_task.name, [r["name"] for r in results])

	def test_stats_count_project_epics_and_stories(self):
		stats = get_project_board(self.project.name, self.epic.name)["stats"]
		# 1 Open Epic, 2 Open Stories in this project's fixtures.
		self.assertEqual(stats["Epic"]["Open"], 1)
		self.assertEqual(stats["Story"]["Open"], 2)
		self.assertEqual(stats["Story"]["Working"], 0)

	def test_story_stat_filter_narrows_lanes_and_cards(self):
		frappe.db.set_value("Task", self.story_a.name, "status", "Working")
		try:
			board = get_project_board(
				self.project.name, self.epic.name, stat_type="Story", stat_status="Working"
			)
			self.assertEqual([s["name"] for s in board["stories"]], [self.story_a.name])
			self.assertEqual(sorted(t["subject"] for t in board["tasks"]), ["WB Task A1", "WB Task A2"])
			# Counts stay project-wide, so the tile does not restate its own filter.
			self.assertEqual(board["stats"]["Story"]["Working"], 1)
		finally:
			frappe.db.set_value("Task", self.story_a.name, "status", "Open")

	def test_epic_stat_filter_matching_nothing_empties_the_board(self):
		board = get_project_board(self.project.name, self.epic.name, stat_type="Epic", stat_status="Working")
		# The one Epic is Open, so an "Epic Working" tile matches no Story at all.
		self.assertEqual(board["stories"], [])
		self.assertEqual(board["tasks"], [])

	def test_stat_filter_ignored_on_a_story_board(self):
		board = get_project_board(
			self.project.name, self.story_a.name, stat_type="Epic", stat_status="Working"
		)
		self.assertEqual(sorted(t["subject"] for t in board["tasks"]), ["WB Task A1", "WB Task A2"])

	def test_sub_task_cannot_be_a_board_root(self):
		with self.assertRaises(frappe.ValidationError):
			get_project_board(self.project.name, self.sub_task.name)


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
		cls.epic = make_task("WB Dept Epic", "Epic", cls.project.name)
		cls.story = make_task("WB Dept Story", "Story", cls.project.name, cls.epic.name)
		cls.open_task = make_task(
			"WB Dept Open", "Task", cls.project.name, cls.story.name, assignees=[cls.user]
		)
		cls.done_task = make_task(
			"WB Dept Done",
			"Task",
			cls.project.name,
			cls.story.name,
			status="Completed",
			assignees=[cls.user],
		)

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
