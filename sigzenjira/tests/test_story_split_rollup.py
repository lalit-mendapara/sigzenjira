import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase


def make_task(subject, work_item_type, parent_task=None, expected_time=0):
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_task_work_item_type": work_item_type,
			"parent_task": parent_task,
			"expected_time": expected_time,
		}
	)
	doc.insert()
	return doc


class TestStorySplitRollup(IntegrationTestCase):
	def test_story_expected_time_is_derived_from_split_rows(self):
		epic = make_task("SR Epic", "Epic", expected_time=10)
		story = make_task("SR Story", "Story", epic.name)  # no expected_time given

		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.append("custom_task_task_split", {"task_item": "T2", "expected_hours": 5})
		story.save()

		self.assertEqual(story.expected_time, 9)

	def test_manual_story_budget_above_split_total_is_kept(self):
		epic = make_task("SR Manual Budget Epic", "Epic", expected_time=50)
		story = make_task("SR Manual Budget Story", "Story", epic.name)

		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()
		self.assertEqual(story.expected_time, 4)

		story.reload()
		story.expected_time = 10
		story.save()
		self.assertEqual(story.expected_time, 10)
		self.assertEqual(story.custom_task_story_budget_is_manual, 1)

		# an unrelated save must not drag it back to the split total
		story.reload()
		story.priority = "High"
		story.save()
		self.assertEqual(story.expected_time, 10)

		# ...nor must a row edit that still fits under it
		story.reload()
		story.custom_task_task_split[0].expected_hours = 6
		story.save()
		self.assertEqual(story.expected_time, 10)

		# a pinned budget is a ceiling - the table may not grow past it
		story.reload()
		story.custom_task_task_split[0].expected_hours = 12
		with self.assertRaises(frappe.ValidationError):
			story.save()

		# raising the Story's own Expected Time is what makes room
		story.reload()
		story.expected_time = 20
		story.custom_task_task_split[0].expected_hours = 12
		story.save()
		self.assertEqual(story.expected_time, 20)
		self.assertEqual(story.custom_task_story_budget_is_manual, 1)

	def test_approved_extra_hours_count_as_allocated_but_never_lock_the_story(self):
		epic = make_task("SR Extra Alloc Epic", "Epic", expected_time=50)
		story = make_task("SR Extra Alloc Story", "Story", epic.name)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()
		story.reload()
		story.expected_time = 6
		story.save()
		story.reload()

		ahr = frappe.get_doc(
			{
				"doctype": "Additional Hours Request",
				"task": story.custom_task_task_split[0].generated_task,
				"additional_hours_requested": 3,
				"reason": "extra hours count as allocated",
			}
		)
		ahr.insert()
		apply_workflow(ahr.as_dict(), "Submit")
		ahr.reload()
		apply_workflow(ahr.as_dict(), "Approve")

		# allocated is now 4 + 3 = 7, past the 6h pin - but the approval put it
		# there, so the Story still saves.
		story.reload()
		story.priority = "High"
		story.save()

		# ...while an edit that pushes allocation up further is still blocked
		story.reload()
		story.custom_task_task_split[0].expected_hours = 5
		with self.assertRaises(frappe.ValidationError):
			story.save()

		# and the budget can't be set below allocated-including-extra either
		story.reload()
		story.expected_time = 6.5
		with self.assertRaises(frappe.ValidationError):
			story.save()

	def test_generated_task_cannot_outgrow_the_pinned_story_budget(self):
		# The other way into the same overrun: edit the child Task instead of
		# the split row, which syncs back into the table on_update.
		epic = make_task("SR Pin Child Epic", "Epic", expected_time=50)
		story = make_task("SR Pin Child Story", "Story", epic.name)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()
		story.reload()
		story.expected_time = 10
		story.save()
		story.reload()

		task = frappe.get_doc("Task", story.custom_task_task_split[0].generated_task)
		task.expected_time = 12
		with self.assertRaises(frappe.ValidationError):
			task.save()

	def test_derived_story_hours_still_cap_later_growth(self):
		# The first split sets the opening number from nothing; after that the
		# Story's hours are a ceiling even though nobody typed them.
		epic = make_task("SR Derived Cap Epic", "Epic", expected_time=50)
		story = make_task("SR Derived Cap Story", "Story", epic.name)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()
		self.assertEqual(story.expected_time, 4)

		story.reload()
		story.append("custom_task_task_split", {"task_item": "T2", "expected_hours": 2})
		with self.assertRaises(frappe.ValidationError):
			story.save()

		# raising the Story's hours in the same save is what lets it through
		story.reload()
		story.expected_time = 6
		story.append("custom_task_task_split", {"task_item": "T2", "expected_hours": 2})
		story.save()
		self.assertEqual(story.expected_time, 6)

		# shrinking the plan never needs permission - and since these hours were
		# never pinned above the table, the Story follows the table down
		story.reload()
		story.custom_task_task_split[1].expected_hours = 1
		story.save()
		self.assertEqual(story.expected_time, 5)

	def test_removing_a_split_row_takes_the_tasks_sub_tasks_with_it(self):
		epic = make_task("SR SubDel Epic", "Epic", expected_time=50)
		story = make_task("SR SubDel Story", "Story", epic.name, expected_time=10)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 3})
		story.save()
		story.reload()

		task = story.custom_task_task_split[0].generated_task
		sub_task = make_task("SR SubDel Sub", "Sub-task", task)

		story.reload()
		story.remove(story.custom_task_task_split[0])
		story.save()

		self.assertFalse(frappe.db.exists("Task", task))
		self.assertFalse(frappe.db.exists("Task", sub_task.name))

	def test_manual_story_budget_below_split_total_is_blocked(self):
		epic = make_task("SR Under Budget Epic", "Epic", expected_time=50)
		story = make_task("SR Under Budget Story", "Story", epic.name)

		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 8})
		story.save()

		story.reload()
		story.expected_time = 5
		with self.assertRaises(frappe.ValidationError):
			story.save()

	def test_manual_budget_survives_generated_task_hour_edit(self):
		epic = make_task("SR Pin Sync Epic", "Epic", expected_time=50)
		story = make_task("SR Pin Sync Story", "Story", epic.name)

		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()
		story.reload()
		story.expected_time = 10
		story.save()
		story.reload()

		task = frappe.get_doc("Task", story.custom_task_task_split[0].generated_task)
		task.expected_time = 3
		task.save()

		story.reload()
		self.assertEqual(story.custom_task_task_split[0].expected_hours, 3)
		self.assertEqual(story.expected_time, 10)

	def test_split_rollup_exceeding_epic_budget_is_blocked(self):
		epic = make_task("SR Over Epic", "Epic", expected_time=5)
		story = make_task("SR Over Story", "Story", epic.name)

		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 3})
		story.append("custom_task_task_split", {"task_item": "T2", "expected_hours": 4})
		with self.assertRaises(frappe.ValidationError):
			story.save()

	def test_generated_task_defaults_to_story_priority(self):
		epic = make_task("SR Prio Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Prio Story",
				"custom_task_work_item_type": "Story",
				"parent_task": epic.name,
				"priority": "High",
			}
		)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.insert()

		story.reload()
		generated_task = story.custom_task_task_split[0].generated_task
		self.assertEqual(frappe.db.get_value("Task", generated_task, "priority"), "High")

	def test_approved_additional_hours_reflect_in_split_row(self):
		epic = make_task("SR AHR Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR AHR Story",
				"custom_task_work_item_type": "Story",
				"parent_task": epic.name,
			}
		)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.insert()

		story.reload()
		generated_task = story.custom_task_task_split[0].generated_task

		ahr = frappe.get_doc(
			{
				"doctype": "Additional Hours Request",
				"task": generated_task,
				"additional_hours_requested": 2,
				"reason": "split rollup test",
			}
		)
		ahr.insert()
		apply_workflow(ahr.as_dict(), "Submit")
		ahr.reload()
		apply_workflow(ahr.as_dict(), "Approve")

		story.reload()
		self.assertEqual(story.custom_task_task_split[0].extra_hours, 2)

	def test_task_expected_time_edit_reflects_in_split_row(self):
		epic = make_task("SR Edit Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Edit Story",
				"custom_task_work_item_type": "Story",
				"parent_task": epic.name,
			}
		)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.insert()

		story.reload()
		generated_task = story.custom_task_task_split[0].generated_task

		task = frappe.get_doc("Task", generated_task)
		task.expected_time = 3
		task.save()

		story.reload()
		self.assertEqual(story.custom_task_task_split[0].expected_hours, 3)
		self.assertEqual(story.expected_time, 3)

	def test_split_row_expected_hours_edit_reflects_in_task(self):
		epic = make_task("SR Row Edit Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Row Edit Story",
				"custom_task_work_item_type": "Story",
				"parent_task": epic.name,
				# room for the row to grow into - Story hours are a ceiling
				"expected_time": 8,
			}
		)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 3})
		story.insert()

		story.reload()
		generated_task = story.custom_task_task_split[0].generated_task
		self.assertEqual(frappe.db.get_value("Task", generated_task, "expected_time"), 3)

		story.custom_task_task_split[0].expected_hours = 5
		story.save()

		self.assertEqual(frappe.db.get_value("Task", generated_task, "expected_time"), 5)

	def test_deleting_task_cleans_up_depends_on_and_deletes_split_row(self):
		epic = make_task("SR Del Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Del Story",
				"custom_task_work_item_type": "Story",
				"parent_task": epic.name,
			}
		)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 3})
		story.append("custom_task_task_split", {"task_item": "T2", "expected_hours": 2})
		story.insert()

		story.reload()
		t1 = story.custom_task_task_split[0].generated_task
		t2 = story.custom_task_task_split[1].generated_task

		# core's populate_depends_on auto-adds a "Task Depends On" row on the
		# Story (the parent) for each child Task created under it.
		story.reload()
		self.assertIn(t1, [row.task for row in story.depends_on])
		self.assertEqual(len(story.custom_task_task_split), 2)

		frappe.delete_doc("Task", t1)

		story.reload()
		self.assertNotIn(t1, [row.task for row in story.depends_on])
		# The row goes too - deleting from either side removes both.
		self.assertEqual([row.generated_task for row in story.custom_task_task_split], [t2])
		self.assertEqual(story.expected_time, 2)

	def test_removing_split_row_deletes_its_generated_task(self):
		epic = make_task("SR RowDel Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR RowDel Story",
				"custom_task_work_item_type": "Story",
				"parent_task": epic.name,
			}
		)
		story.append("custom_task_task_split", {"task_item": "Keep", "expected_hours": 3})
		story.append("custom_task_task_split", {"task_item": "Drop", "expected_hours": 2})
		story.insert()

		story.reload()
		keep_task = story.custom_task_task_split[0].generated_task
		drop_task = story.custom_task_task_split[1].generated_task

		story.remove(story.custom_task_task_split[1])
		story.save()

		self.assertFalse(frappe.db.exists("Task", drop_task))
		self.assertTrue(frappe.db.exists("Task", keep_task))

		story.reload()
		self.assertEqual([row.generated_task for row in story.custom_task_task_split], [keep_task])
		self.assertEqual(story.expected_time, 3)

	def test_non_privileged_user_cannot_add_split_row(self):
		user = "test_split_row_employee@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": "Split Row Employee",
					"send_welcome_email": 0,
					"roles": [{"role": "Employee"}, {"role": "Projects User"}],
				}
			).insert(ignore_permissions=True)

		epic = make_task("SR Perm Epic", "Epic", expected_time=10)
		story = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Perm Story",
				"custom_task_work_item_type": "Story",
				"parent_task": epic.name,
			}
		)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 3})
		story.insert()
		story.reload()

		frappe.set_user(user)
		try:
			story_as_employee = frappe.get_doc("Task", story.name)
			story_as_employee.append("custom_task_task_split", {"task_item": "T2", "expected_hours": 2})
			with self.assertRaises(frappe.ValidationError):
				story_as_employee.save()
		finally:
			frappe.set_user("Administrator")

	def test_first_manual_task_under_an_unsplit_story_gets_a_row(self):
		# The Story form's "Create Task" button lands here - no split rows yet,
		# and the mirrored row is what puts the work on the Story's plan.
		epic = make_task("SR Manual Epic", "Epic", expected_time=10)
		story = make_task("SR Manual Story", "Story", epic.name)

		task = make_task("SR Manual Task", "Task", story.name, expected_time=2)

		story.reload()
		self.assertEqual(len(story.custom_task_task_split), 1)
		self.assertEqual(story.custom_task_task_split[0].generated_task, task.name)
		self.assertEqual(story.custom_task_task_split[0].expected_hours, 2)
		# Nothing was declared on the Story, so the row sets the opening number.
		self.assertEqual(story.expected_time, 2)

	def test_first_manual_task_does_not_shrink_a_declared_story_budget(self):
		# The case the old block_manual_task_under_story guard existed for:
		# custom_task_story_budget_is_manual now pins the declared ceiling instead.
		epic = make_task("SR Declared Epic", "Epic", expected_time=40)
		story = make_task("SR Declared Story", "Story", epic.name, expected_time=12)

		make_task("SR Declared Task", "Task", story.name, expected_time=3)

		story.reload()
		self.assertEqual(story.expected_time, 12)
		self.assertEqual(len(story.custom_task_task_split), 1)

	def test_manual_task_under_a_split_story_gets_its_own_row(self):
		epic = make_task("SR Mirror Epic", "Epic", expected_time=50)
		story = make_task("SR Mirror Story", "Story", epic.name, expected_time=10)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()
		story.reload()

		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "SR Mirror Extra Task",
				"custom_task_work_item_type": "Task",
				"parent_task": story.name,
				"expected_time": 3,
				# what a Text Editor field actually stores
				"description": '<div class="ql-editor read-mode"><p>Build the thing</p></div>',
			}
		).insert()

		story.reload()
		rows = {row.generated_task: row for row in story.custom_task_task_split}
		self.assertIn(task.name, rows)
		self.assertEqual(rows[task.name].task_item, "SR Mirror Extra Task")
		self.assertEqual(rows[task.name].description, "Build the thing")
		self.assertEqual(rows[task.name].expected_hours, 3)
		# the declared 10h ceiling stands; 7h of it is now allocated
		self.assertEqual(story.expected_time, 10)

	def test_manual_task_breaching_a_pinned_story_budget_is_blocked(self):
		epic = make_task("SR Mirror Pin Epic", "Epic", expected_time=50)
		story = make_task("SR Mirror Pin Story", "Story", epic.name)
		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()
		story.reload()
		story.expected_time = 6
		story.save()

		with self.assertRaises(frappe.ValidationError):
			make_task("SR Mirror Pin Task", "Task", story.name, expected_time=3)

	def test_standalone_task_still_allowed(self):
		task = make_task("SR Standalone Task", "Task", expected_time=2)
		self.assertTrue(frappe.db.exists("Task", task.name))

	def test_split_generated_task_still_saves(self):
		epic = make_task("SR Gen Epic", "Epic", expected_time=10)
		story = make_task("SR Gen Story", "Story", epic.name)

		story.append("custom_task_task_split", {"task_item": "T1", "expected_hours": 4})
		story.save()
		story.reload()

		generated_task = story.custom_task_task_split[0].generated_task
		self.assertTrue(generated_task)

		# a later edit to the generated Task must not trip the guard
		task = frappe.get_doc("Task", generated_task)
		task.expected_time = 3
		task.save()
		self.assertEqual(frappe.db.get_value("Task", generated_task, "expected_time"), 3)
