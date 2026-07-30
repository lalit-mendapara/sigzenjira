import json

import frappe
from frappe.desk.form import assign_to
from frappe.tests import IntegrationTestCase

from sigzenjira.install import add_task_tracker_workspace_shortcut
from sigzenjira.sigzenjira.task_tracker import get_tracker_data

MANAGER_USER = "test_tracker_manager@example.com"
EMPLOYEE_USER = "test_tracker_employee@example.com"
OTHER_EMPLOYEE_USER = "test_tracker_other_employee@example.com"


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


def make_task(subject, project=None, assignee=None, work_item_type="Task", parent_task=None):
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_work_item_type": work_item_type,
			"project": project,
			"parent_task": parent_task,
		}
	)
	doc.insert(ignore_permissions=True)
	if assignee:
		assign_to.add({"assign_to": [assignee], "doctype": "Task", "name": doc.name})
	return doc


def ensure_project(project_name):
	existing = frappe.db.get_value("Project", {"project_name": project_name})
	if existing:
		return existing
	return (
		frappe.get_doc({"doctype": "Project", "project_name": project_name})
		.insert(ignore_permissions=True)
		.name
	)


def _find_epic(epics, name):
	found = next((e for e in epics if e["name"] == name), None)
	assert found is not None, f"epic {name!r} not found in {[e['name'] for e in epics]}"
	return found


def _find_story(stories, name):
	found = next((s for s in stories if s["name"] == name), None)
	assert found is not None, f"story {name!r} not found in {[s['name'] for s in stories]}"
	return found


class TestTaskTracker(IntegrationTestCase):
	def test_epic_story_task_nest_with_correct_totals(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		project = ensure_project("TT Hierarchy Project")

		epic = make_task("TT Epic", project=project, work_item_type="Epic")
		story = make_task("TT Story", project=project, work_item_type="Story", parent_task=epic.name)
		make_task(
			"TT Task 1", project=project, work_item_type="Task", parent_task=story.name, assignee=employee
		)
		make_task(
			"TT Task 2", project=project, work_item_type="Task", parent_task=story.name, assignee=employee
		)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project)
		finally:
			frappe.set_user("Administrator")

		found_epic = _find_epic(data["epics"], epic.name)
		self.assertEqual(found_epic["subject"], "TT Epic")
		self.assertNotIn("story_total", found_epic)

		found_story = _find_story(found_epic["stories"], story.name)
		self.assertEqual(found_story["subject"], "TT Story")
		self.assertEqual(found_story["task_total"], 2)
		task_subjects = {t["subject"] for t in found_story["tasks"]}
		self.assertEqual(task_subjects, {"TT Task 1", "TT Task 2"})

	def test_sub_task_never_appears_in_payload(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		project = ensure_project("TT Subtask Project")

		epic = make_task("TT Subtask Epic", project=project, work_item_type="Epic")
		story = make_task("TT Subtask Story", project=project, work_item_type="Story", parent_task=epic.name)
		task = make_task("TT Subtask Task", project=project, work_item_type="Task", parent_task=story.name)
		make_task("TT Subtask Child", project=project, work_item_type="Sub-task", parent_task=task.name)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project)
		finally:
			frappe.set_user("Administrator")

		found_story = _find_story(_find_epic(data["epics"], epic.name)["stories"], story.name)
		self.assertEqual(found_story["task_total"], 1)
		task_subjects = {t["subject"] for t in found_story["tasks"]}
		self.assertNotIn("TT Subtask Child", task_subjects)

	def test_epic_less_story_buckets_under_no_epic(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		project = ensure_project("TT Orphan Story Project")

		orphan_story = make_task("TT Orphan Story", project=project, work_item_type="Story")
		make_task(
			"TT Orphan Story Task", project=project, work_item_type="Task", parent_task=orphan_story.name
		)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project)
		finally:
			frappe.set_user("Administrator")

		no_epic = next((e for e in data["epics"] if e["name"] is None), None)
		assert no_epic is not None, "synthetic 'No Epic' bucket missing"
		self.assertEqual(no_epic["subject"], "No Epic")
		found_story = _find_story(no_epic["stories"], orphan_story.name)
		self.assertEqual(found_story["subject"], "TT Orphan Story")
		self.assertEqual(found_story["task_total"], 1)

	def test_story_less_task_buckets_under_no_epic_no_story(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		project = ensure_project("TT Orphan Task Project")

		make_task("TT Orphan Task", project=project, work_item_type="Task")

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project)
		finally:
			frappe.set_user("Administrator")

		no_epic = next((e for e in data["epics"] if e["name"] is None), None)
		assert no_epic is not None, "synthetic 'No Epic' bucket missing"
		no_story = next((s for s in no_epic["stories"] if s["name"] is None), None)
		assert no_story is not None, "synthetic 'No Story' row missing"
		self.assertEqual(no_story["subject"], "No Story")
		task_subjects = {t["subject"] for t in no_story["tasks"]}
		self.assertIn("TT Orphan Task", task_subjects)

	def test_manager_sees_every_employees_tasks_in_tree(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		other = ensure_user(OTHER_EMPLOYEE_USER, "Tracker Other", ["Projects User"])
		project = ensure_project("TT Manager Visibility Project")

		epic = make_task("TT Visibility Epic", project=project, work_item_type="Epic")
		story = make_task(
			"TT Visibility Story", project=project, work_item_type="Story", parent_task=epic.name
		)
		make_task(
			"TT Visibility Task 1",
			project=project,
			work_item_type="Task",
			parent_task=story.name,
			assignee=employee,
		)
		make_task(
			"TT Visibility Task 2",
			project=project,
			work_item_type="Task",
			parent_task=story.name,
			assignee=other,
		)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project)
		finally:
			frappe.set_user("Administrator")

		found_story = _find_story(_find_epic(data["epics"], epic.name)["stories"], story.name)
		all_assignees = {a for t in found_story["tasks"] for a in t["assignees"]}
		self.assertIn(employee, all_assignees)
		self.assertIn(other, all_assignees)

	def test_employee_only_sees_own_task_but_real_parent_headers(self):
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		other = ensure_user(OTHER_EMPLOYEE_USER, "Tracker Other", ["Projects User"])
		project = ensure_project("TT Employee Visibility Project")

		epic = make_task("TT Employee Epic", project=project, work_item_type="Epic")
		story = make_task("TT Employee Story", project=project, work_item_type="Story", parent_task=epic.name)
		make_task(
			"TT Employee Own Task",
			project=project,
			work_item_type="Task",
			parent_task=story.name,
			assignee=employee,
		)
		make_task(
			"TT Employee Other Task",
			project=project,
			work_item_type="Task",
			parent_task=story.name,
			assignee=other,
		)

		frappe.set_user(employee)
		try:
			data = get_tracker_data(project=project)
		finally:
			frappe.set_user("Administrator")

		found_epic = _find_epic(data["epics"], epic.name)
		self.assertEqual(found_epic["subject"], "TT Employee Epic")
		found_story = _find_story(found_epic["stories"], story.name)
		self.assertEqual(found_story["subject"], "TT Employee Story")
		task_subjects = {t["subject"] for t in found_story["tasks"]}
		self.assertEqual(task_subjects, {"TT Employee Own Task"})

	def test_non_manager_gets_empty_epics_for_project_with_no_own_tasks(self):
		# get_tracker_data is whitelisted with a caller-supplied `project` - a plain
		# Projects User must not be able to read Epic/Story subjects/status for a
		# project they have no assigned Task in, just by naming it.
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		other = ensure_user(OTHER_EMPLOYEE_USER, "Tracker Other", ["Projects User"])
		project = ensure_project("TT Disclosure Project")

		epic = make_task("TT Disclosure Epic", project=project, work_item_type="Epic")
		story = make_task(
			"TT Disclosure Story", project=project, work_item_type="Story", parent_task=epic.name
		)
		make_task(
			"TT Disclosure Other Task",
			project=project,
			work_item_type="Task",
			parent_task=story.name,
			assignee=other,
		)

		frappe.set_user(employee)
		try:
			data = get_tracker_data(project=project)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(data["epics"], [])

	def test_tasks_outside_project_are_excluded(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		project_a = ensure_project("TT Cross Project A")
		project_b = ensure_project("TT Cross Project B")

		epic_a = make_task("TT Cross Epic A", project=project_a, work_item_type="Epic")
		story_a = make_task(
			"TT Cross Story A", project=project_a, work_item_type="Story", parent_task=epic_a.name
		)
		make_task("TT Cross Task A", project=project_a, work_item_type="Task", parent_task=story_a.name)

		epic_b = make_task("TT Cross Epic B", project=project_b, work_item_type="Epic")
		story_b = make_task(
			"TT Cross Story B", project=project_b, work_item_type="Story", parent_task=epic_b.name
		)
		make_task("TT Cross Task B", project=project_b, work_item_type="Task", parent_task=story_b.name)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project_a)
		finally:
			frappe.set_user("Administrator")

		epic_names = {e["name"] for e in data["epics"]}
		self.assertIn(epic_a.name, epic_names)
		self.assertNotIn(epic_b.name, epic_names)

	def test_epic_outside_project_still_surfaces_its_story_under_no_epic(self):
		# Epic has no project (or a different one) but its Story is in the queried
		# project - the Story (and its Task) must not vanish just because their
		# Epic ancestor didn't survive the project filter.
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		project = ensure_project("TT Coercion Project")

		foreign_epic = make_task("TT Foreign Epic", project=None, work_item_type="Epic")
		story = make_task(
			"TT Coerced Story", project=project, work_item_type="Story", parent_task=foreign_epic.name
		)
		make_task("TT Coerced Task", project=project, work_item_type="Task", parent_task=story.name)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project)
		finally:
			frappe.set_user("Administrator")

		no_epic = next((e for e in data["epics"] if e["name"] is None), None)
		assert no_epic is not None, "synthetic 'No Epic' bucket missing - the coerced Story vanished"
		found_story = _find_story(no_epic["stories"], story.name)
		self.assertEqual(found_story["task_total"], 1)

	def test_project_and_employee_counts_are_task_type_only(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		project = ensure_project("TT Count Project")

		epic = make_task("TT Count Epic", project=project, work_item_type="Epic")
		story = make_task("TT Count Story", project=project, work_item_type="Story", parent_task=epic.name)
		make_task(
			"TT Count Task", project=project, work_item_type="Task", parent_task=story.name, assignee=employee
		)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project)
		finally:
			frappe.set_user("Administrator")

		found_project = next((p for p in data["projects"] if p["name"] == project), None)
		assert found_project is not None, f"project {project!r} not found in {data['projects']}"
		self.assertEqual(found_project["task_count"], 1)

		found_employee = next((e for e in data["employees"] if e["name"] == employee), None)
		assert found_employee is not None, f"employee {employee!r} not found in {data['employees']}"
		self.assertEqual(found_employee["task_count"], 1)

	def test_employees_empty_when_no_project(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])

		make_task("TT No Project Employees", assignee=employee)

		frappe.set_user(manager)
		try:
			data = get_tracker_data()
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(data["employees"], [])
		self.assertEqual(data["epics"], [])

	def test_employees_scoped_to_selected_project(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		other = ensure_user(OTHER_EMPLOYEE_USER, "Tracker Other", ["Projects User"])
		project_a = ensure_project("TT Roster Project A - scoped test")
		project_b = ensure_project("TT Roster Project B - scoped test")

		make_task("TT Roster A Task", project=project_a, assignee=employee)
		make_task("TT Roster B Task", project=project_b, assignee=other)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project_a)
		finally:
			frappe.set_user("Administrator")

		employee_names = {e["name"] for e in data["employees"]}
		self.assertEqual(employee_names, {employee})

	def test_employee_role_only_sees_self_in_project_employees(self):
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		other = ensure_user(OTHER_EMPLOYEE_USER, "Tracker Other", ["Projects User"])
		project_a = ensure_project("TT Roster Project A - self test")

		make_task("TT Roster Own", project=project_a, assignee=employee)
		make_task("TT Roster Other In Same Project", project=project_a, assignee=other)

		frappe.set_user(employee)
		try:
			data = get_tracker_data(project=project_a)
		finally:
			frappe.set_user("Administrator")

		employee_names = {e["name"] for e in data["employees"]}
		self.assertEqual(employee_names, {employee})

	def test_sidebar_totals_are_unfiltered_by_current_selection(self):
		manager = ensure_user(MANAGER_USER, "Tracker Manager", ["Projects Manager"])
		employee = ensure_user(EMPLOYEE_USER, "Tracker Employee", ["Projects User"])
		project_a = ensure_project("TT Project A")
		project_b = ensure_project("TT Project B")

		make_task("TT Sidebar A", project=project_a, assignee=employee)
		make_task("TT Sidebar B", project=project_b, assignee=employee)

		frappe.set_user(manager)
		try:
			data = get_tracker_data(project=project_a)
		finally:
			frappe.set_user("Administrator")

		project_names = {p["name"] for p in data["projects"]}
		self.assertIn(project_a, project_names)
		self.assertIn(project_b, project_names)


class TestTaskTrackerWorkspaceShortcut(IntegrationTestCase):
	def test_shortcut_link_to_points_at_existing_page(self):
		add_task_tracker_workspace_shortcut()
		self.assertTrue(frappe.db.exists("Page", "task-tracker"))

	def test_creates_shortcut_once_and_is_idempotent(self):
		add_task_tracker_workspace_shortcut()
		count_after_first = frappe.db.count(
			"Workspace Shortcut", {"parent": "Project Management", "link_to": "task-tracker"}
		)
		self.assertEqual(count_after_first, 1)

		add_task_tracker_workspace_shortcut()
		count_after_second = frappe.db.count(
			"Workspace Shortcut", {"parent": "Project Management", "link_to": "task-tracker"}
		)
		self.assertEqual(count_after_second, 1)

		content = json.loads(frappe.db.get_value("Workspace", "Project Management", "content") or "[]")
		shortcut_blocks = [
			b
			for b in content
			if b.get("type") == "shortcut" and b.get("data", {}).get("shortcut_name") == "Task Tracker"
		]
		self.assertEqual(len(shortcut_blocks), 1)
