import frappe
from frappe.tests import IntegrationTestCase

from sigzenjira.sigzenjira.page.work_board.work_board import _current_steps, get_project_board

from .test_status_cascade import make_task_under_story
from .test_work_board import make_project, make_task


class TestWorkBoardCurrentStep(IntegrationTestCase):
	"""The Story chip's current step: lowest-idx split row that generated a Task
	still open. Ungenerated rows and Completed/Cancelled Tasks are both skipped."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.project = make_project("WB Step Project", [])
		cls.epic = make_task("WB Step Epic", "Epic", cls.project.name, expected_time=100)
		cls.story = make_task(
			"WB Step Story", "Story", cls.project.name, cls.epic.name, expected_time=20
		)

		# Row 1 has no hours, so generate_tasks_from_split leaves it ungenerated -
		# it must not hold back row 3 from being the current step.
		cls.story.append("custom_task_task_split", {"task_item": "WB Step Plan", "expected_hours": 0})
		cls.story.save()

		cls.done = make_task_under_story(cls.story, "WB Step Design", 1, status="Completed")
		cls.current = make_task_under_story(cls.story, "WB Step Develop", 1, status="Working")
		cls.later = make_task_under_story(cls.story, "WB Step Ship", 1)

	def tearDown(self):
		frappe.set_user("Administrator")

	def set_status(self, task, status):
		# Fixtures are built once per class, so every write puts back what it
		# found or it leaks into whichever test runs next.
		before = frappe.db.get_value("Task", task, "status")
		frappe.db.set_value("Task", task, "status", status)
		self.addCleanup(frappe.db.set_value, "Task", task, "status", before)

	def step(self):
		return _current_steps([self.story.name]).get(self.story.name)

	def test_first_open_generated_row_wins(self):
		step = self.step()
		# idx 1 is the ungenerated row, idx 2 is Completed - idx 3 is the answer.
		self.assertEqual(step["idx"], 3)
		self.assertEqual(step["task_item"], "WB Step Develop")
		self.assertEqual(step["task"], self.current.name)
		self.assertEqual(step["status"], "Working")

	def test_cancelled_is_skipped_like_completed(self):
		self.set_status(self.current.name, "Cancelled")
		step = self.step()
		self.assertEqual(step["idx"], 4)
		self.assertEqual(step["task"], self.later.name)

	def test_no_step_once_every_generated_row_is_closed(self):
		for task in (self.current.name, self.later.name):
			self.set_status(task, "Completed")
		# Row 1 is still ungenerated, and planned work is not work in flight.
		self.assertIsNone(self.step())

	def test_story_with_no_split_rows_has_no_step(self):
		bare = make_task("WB Step Bare Story", "Story", self.project.name, self.epic.name)
		self.assertEqual(_current_steps([bare.name]), {})

	def test_empty_story_list_never_queries(self):
		self.assertEqual(_current_steps([]), {})

	def test_board_ships_the_step_on_the_story_row(self):
		stories = {s["name"]: s for s in get_project_board(self.project.name)["stories"]}
		self.assertEqual(stories[self.story.name]["current_step"]["task"], self.current.name)
