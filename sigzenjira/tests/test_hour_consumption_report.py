import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from sigzenjira.sigzenjira.report.project_hour_consumption.project_hour_consumption import execute

from .test_status_cascade import make_task, make_task_under_story

REPORT_PO = "test_hcr_po@example.com"
REPORT_OUTSIDER = "test_hcr_outsider@example.com"


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


def make_billable_project(name):
	# Project autonames off `naming_series` (PROJ-####), not project_name, so
	# the exists-check has to look up the docname via project_name - checking
	# by `name` directly never matches and IntegrationTestCase only rolls back
	# once per class, not per test, so a stale row from an earlier test method
	# in this run would otherwise collide on project_name's unique constraint.
	existing = frappe.db.exists("Project", {"project_name": name})
	if existing:
		# Frappe reverts a naming_series counter when the deleted doc was the
		# last one minted with it (revert_series_if_last), so the Project
		# recreated below gets this exact same docname back - any Tasks an
		# earlier test method already created against it would otherwise leak
		# straight into this method's tree query.
		frappe.db.delete("Task", {"project": existing})
		frappe.delete_doc("Project", existing, force=True, ignore_permissions=True)
	return frappe.get_doc({"doctype": "Project", "project_name": name, "custom_is_billable": 1}).insert(
		ignore_permissions=True
	)


class TestHourConsumptionReportGuards(IntegrationTestCase):
	def setUp(self):
		self.project = make_billable_project("HCR Guards Project")

	def test_missing_project_throws(self):
		with self.assertRaises(frappe.ValidationError):
			execute({})

	def test_outsider_gets_permission_error(self):
		user = ensure_user(REPORT_OUTSIDER, "HCR Outsider", ["Projects User"])
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				execute({"project": self.project.name})
		finally:
			frappe.set_user("Administrator")

	def test_story_from_another_project_throws(self):
		other = make_billable_project("HCR Guards Other Project")
		epic = make_task("HCR Guards Epic", "Epic", project=other.name, is_billable=1)
		story = make_task("HCR Guards Story", "Story", epic.name, project=other.name, is_billable=1)

		with self.assertRaises(frappe.ValidationError):
			execute({"project": self.project.name, "story": story.name})

	def test_inverted_date_range_throws(self):
		with self.assertRaises(frappe.ValidationError):
			execute({"project": self.project.name, "from_date": "2026-07-31", "to_date": "2026-07-01"})

	def test_product_owner_reads_a_project_they_are_not_on(self):
		# The bypass widening from Task 1, asserted at the report's own door.
		if not frappe.db.exists("Role", "Product Owner"):
			frappe.get_doc({"doctype": "Role", "role_name": "Product Owner"}).insert(ignore_permissions=True)

		user = ensure_user(REPORT_PO, "HCR Product Owner", ["Projects User", "Product Owner"])
		frappe.set_user(user)
		try:
			_columns, data, _message, _chart, _summary = execute({"project": self.project.name})
			self.assertEqual(data, [])
		finally:
			frappe.set_user("Administrator")

	def test_valid_filters_return_columns_and_no_rows(self):
		columns, data, _message, _chart, _summary = execute({"project": self.project.name})
		self.assertEqual(data, [])
		self.assertEqual([c["fieldname"] for c in columns][:3], ["work_item", "subject", "work_item_type"])


def make_employee(first_name):
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	return frappe.get_doc(
		{
			"doctype": "Employee",
			# Activity Cost's own uniqueness check keys off employee_name, not the
			# employee id (activity_cost.py:check_unique), and IntegrationTestCase
			# only rolls back once per class - every test method's setUp calls
			# make_employee with this same literal "HCR Tree Tester", so without a
			# per-call suffix the second method's Activity Cost insert collides
			# with the first method's leftover row for a different employee id.
			"first_name": f"{first_name} {frappe.generate_hash(length=6)}",
			"company": company,
			"status": "Active",
			"gender": "Male",
			"date_of_birth": "1995-01-01",
			"date_of_joining": "2024-01-01",
		}
	).insert()


def log_hours(employee, task_name, hours, date, submit=True):
	# Timesheet.validate_overlap rejects two rows for the same employee whose
	# time windows overlap (timesheet.py:get_overlap_for, docstatus < 2) - every
	# call in this suite logs against the same employee/date, so each entry has
	# to start after whatever is already logged that day rather than always at
	# a fixed 09:00.
	last_end = frappe.db.sql(
		"""
		select max(td.to_time) from `tabTimesheet Detail` td
		join `tabTimesheet` ts on ts.name = td.parent
		where ts.employee = %s and ts.docstatus < 2 and date(td.from_time) = %s
		""",
		(employee.name, date),
	)[0][0]
	from_time = last_end or f"{date} 09:00:00"
	timesheet = frappe.get_doc(
		{
			"doctype": "Timesheet",
			"employee": employee.name,
			"time_logs": [
				{
					"activity_type": "Execution",
					"task": task_name,
					"from_time": from_time,
					"hours": hours,
					"is_billable": 1,
				}
			],
		}
	).insert()
	if submit:
		timesheet.submit()
	return timesheet


def rows_by_work_item(data):
	return {row["work_item"]: row for row in data}


class TestHourConsumptionReportTree(IntegrationTestCase):
	def setUp(self):
		self.project = make_billable_project("HCR Tree Project")
		self.employee = make_employee("HCR Tree Tester")

		if not frappe.db.exists("Activity Cost", {"employee": self.employee.name}):
			frappe.get_doc(
				{
					"doctype": "Activity Cost",
					"employee": self.employee.name,
					"activity_type": "Execution",
					"costing_rate": 100,
					"billing_rate": 150,
				}
			).insert()

		self.epic = make_task(
			"HCR Tree Epic", "Epic", project=self.project.name, expected_time=20, is_billable=1
		)
		self.story = make_task(
			"HCR Tree Story",
			"Story",
			self.epic.name,
			project=self.project.name,
			expected_time=10,
			is_billable=1,
		)
		# A Story's Tasks may only come from its Task Split grid
		# (custom/task.py:block_manual_task_under_story).
		self.billable_task = make_task_under_story(self.story, "HCR Billable", 5, is_billable=1)
		self.non_billable_task = make_task_under_story(self.story, "HCR Non Billable", 5, is_billable=0)

		log_hours(self.employee, self.billable_task.name, 4, today())
		log_hours(self.employee, self.non_billable_task.name, 3, today())

	def test_rows_are_parent_before_child_with_indent(self):
		_columns, data, _message, _chart, _summary = execute({"project": self.project.name})
		order = [row["work_item"] for row in data]

		self.assertEqual(order[0], self.epic.name)
		self.assertEqual(order[1], self.story.name)
		self.assertEqual(set(order[2:]), {self.billable_task.name, self.non_billable_task.name})

		rows = rows_by_work_item(data)
		self.assertEqual(rows[self.epic.name]["indent"], 0)
		self.assertEqual(rows[self.story.name]["indent"], 1)
		self.assertEqual(rows[self.billable_task.name]["indent"], 2)

		# An emitted root must not point at a parent outside the emitted set,
		# or the datatable hides it.
		self.assertEqual(rows[self.epic.name]["parent_task"], "")

	def test_hours_roll_up_and_split_billable(self):
		_columns, data, _message, _chart, _summary = execute({"project": self.project.name})
		rows = rows_by_work_item(data)

		self.assertEqual(rows[self.epic.name]["actual_time"], 7)
		self.assertEqual(rows[self.epic.name]["billable_hours"], 4)
		self.assertEqual(rows[self.epic.name]["non_billable_hours"], 3)
		# 4 billable hours * billing_rate 150
		self.assertEqual(rows[self.epic.name]["billing_amount"], 600)

		for row in data:
			self.assertAlmostEqual(
				row["billable_hours"] + row["non_billable_hours"], row["actual_time"], places=4
			)

	def test_matches_stored_rollup_when_undated(self):
		# Read-time aggregation and recompute_actual_time's stored rollup must
		# agree; a divergence is a rollup bug this report would surface.
		_columns, data, _message, _chart, _summary = execute({"project": self.project.name})
		rows = rows_by_work_item(data)
		self.assertEqual(
			rows[self.story.name]["actual_time"],
			frappe.db.get_value("Task", self.story.name, "actual_time"),
		)

	def test_variance_is_signed(self):
		_columns, data, _message, _chart, _summary = execute({"project": self.project.name})
		rows = rows_by_work_item(data)
		# Story: 10 expected, 7 actual - under budget must read negative, which
		# Task.custom_actual_extra_hours (clamped at 0) could never show.
		self.assertEqual(rows[self.story.name]["variance"], -3)

	def test_draft_timesheets_excluded(self):
		log_hours(self.employee, self.billable_task.name, 8, today(), submit=False)
		_columns, data, _message, _chart, _summary = execute({"project": self.project.name})
		rows = rows_by_work_item(data)
		self.assertEqual(rows[self.billable_task.name]["actual_time"], 4)

	def test_story_filter_returns_that_subtree_only(self):
		_columns, data, _message, _chart, _summary = execute(
			{"project": self.project.name, "story": self.story.name}
		)
		rows = rows_by_work_item(data)

		self.assertNotIn(self.epic.name, rows)
		self.assertEqual(rows[self.story.name]["indent"], 0)
		self.assertEqual(rows[self.story.name]["parent_task"], "")

	def test_reparented_task_still_appears(self):
		# Names encode the hierarchy but reparenting deliberately does not
		# rename, so this Sub-task keeps a name prefixed by Story 1 while
		# actually living under Story 2. A name-prefix query filtered on
		# Story 2 would silently drop it; a parent_task walk finds it.
		second_story = make_task(
			"HCR Tree Story 2",
			"Story",
			self.epic.name,
			project=self.project.name,
			expected_time=4,
			is_billable=1,
		)
		second_task = make_task_under_story(second_story, "HCR Second", 4, is_billable=1)

		stray = make_task(
			"HCR Stray", "Sub-task", self.billable_task.name, project=self.project.name, is_billable=1
		)
		self.assertTrue(stray.name.startswith(self.billable_task.name))

		stray.parent_task = second_task.name
		stray.save()

		_columns, data, _message, _chart, _summary = execute(
			{"project": self.project.name, "story": second_story.name}
		)
		self.assertIn(stray.name, rows_by_work_item(data))


class TestHourConsumptionReportDateRange(IntegrationTestCase):
	def setUp(self):
		self.project = make_billable_project("HCR Dates Project")
		self.employee = make_employee("HCR Dates Tester")

		self.epic = make_task(
			"HCR Dates Epic", "Epic", project=self.project.name, expected_time=20, is_billable=1
		)
		self.story = make_task(
			"HCR Dates Story",
			"Story",
			self.epic.name,
			project=self.project.name,
			expected_time=10,
			is_billable=1,
		)
		self.task = make_task_under_story(self.story, "HCR Dated", 5, is_billable=1)

		self.old_day = add_days(today(), -10)
		log_hours(self.employee, self.task.name, 6, self.old_day)
		log_hours(self.employee, self.task.name, 2, today())

	def test_range_excludes_out_of_range_hours_and_parents_shrink(self):
		_columns, data, _message, _chart, _summary = execute(
			{"project": self.project.name, "from_date": today(), "to_date": today()}
		)
		rows = rows_by_work_item(data)

		self.assertEqual(rows[self.task.name]["actual_time"], 2)
		# The range must apply before the rollup, not after.
		self.assertEqual(rows[self.epic.name]["actual_time"], 2)

	def test_from_date_alone_means_since(self):
		_columns, data, _message, _chart, _summary = execute(
			{"project": self.project.name, "from_date": today()}
		)
		self.assertEqual(rows_by_work_item(data)[self.task.name]["actual_time"], 2)

	def test_to_date_alone_means_up_to(self):
		_columns, data, _message, _chart, _summary = execute(
			{"project": self.project.name, "to_date": self.old_day}
		)
		self.assertEqual(rows_by_work_item(data)[self.task.name]["actual_time"], 6)

	def test_to_date_includes_work_logged_late_that_day(self):
		# from_time is a datetime, so `from_time <= to_date` would silently drop
		# everything logged after midnight on the last day of the range.
		late = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"employee": self.employee.name,
				"time_logs": [
					{
						"activity_type": "Execution",
						"task": self.task.name,
						"from_time": f"{today()} 22:30:00",
						"hours": 1,
						"is_billable": 1,
					}
				],
			}
		).insert()
		late.submit()

		_columns, data, _message, _chart, _summary = execute(
			{"project": self.project.name, "from_date": today(), "to_date": today()}
		)
		self.assertEqual(rows_by_work_item(data)[self.task.name]["actual_time"], 3)

	def test_expected_time_is_not_date_scoped(self):
		_columns, data, _message, _chart, _summary = execute(
			{"project": self.project.name, "from_date": today(), "to_date": today()}
		)
		# Estimates have no date dimension - they stay whole-life, which is why
		# the report carries a banner saying so (see the message test).
		# Story.expected_time is 5, not the 10 passed to make_task: setUp's
		# single make_task_under_story call appends one custom_task_split row
		# with expected_hours=5, and rollup_story_expected_time (task.py:303)
		# overwrites expected_time with the split-row sum as soon as any split
		# row exists.
		self.assertEqual(rows_by_work_item(data)[self.story.name]["expected_time"], 5)


class TestHourConsumptionReportBillableOnly(IntegrationTestCase):
	def setUp(self):
		self.project = make_billable_project("HCR Billable Only Project")
		self.employee = make_employee("HCR Billable Only Tester")

		self.epic = make_task(
			"HCR BO Epic", "Epic", project=self.project.name, expected_time=20, is_billable=1
		)
		self.story = make_task(
			"HCR BO Story",
			"Story",
			self.epic.name,
			project=self.project.name,
			expected_time=10,
			is_billable=1,
		)
		self.billable_task = make_task_under_story(self.story, "HCR BO Billable", 5, is_billable=1)
		self.non_billable_task = make_task_under_story(self.story, "HCR BO Non Billable", 5, is_billable=0)

		log_hours(self.employee, self.billable_task.name, 4, today())
		log_hours(self.employee, self.non_billable_task.name, 3, today())

	def test_non_billable_rows_dropped_and_parents_shrink(self):
		_columns, data, _message, _chart, _summary = execute(
			{"project": self.project.name, "billable_only": 1}
		)
		rows = rows_by_work_item(data)

		self.assertNotIn(self.non_billable_task.name, rows)
		self.assertIn(self.billable_task.name, rows)
		# The Story's totals must cover only what is still on screen.
		self.assertEqual(rows[self.story.name]["actual_time"], 4)
		self.assertEqual(rows[self.story.name]["non_billable_hours"], 0)

	def test_unset_shows_everything(self):
		_columns, data, _message, _chart, _summary = execute({"project": self.project.name})
		self.assertIn(self.non_billable_task.name, rows_by_work_item(data))

	def test_billable_descendant_keeps_its_non_billable_ancestor(self):
		# The one-way clamp forbids this state, so it should never occur - but a
		# blanket "drop every non-billable node" would swallow billable hours if
		# legacy data ever violated it.
		frappe.db.set_value("Task", self.story.name, "custom_is_billable", 0)
		frappe.db.commit()
		try:
			_columns, data, _message, _chart, _summary = execute(
				{"project": self.project.name, "billable_only": 1}
			)
			rows = rows_by_work_item(data)
			self.assertIn(self.story.name, rows)
			self.assertIn(self.billable_task.name, rows)
		finally:
			frappe.db.set_value("Task", self.story.name, "custom_is_billable", 1)
			frappe.db.commit()


class TestHourConsumptionReportSummary(IntegrationTestCase):
	def setUp(self):
		self.project = make_billable_project("HCR Summary Project")
		self.employee = make_employee("HCR Summary Tester")

		self.epic_a = make_task(
			"HCR Sum Epic A", "Epic", project=self.project.name, expected_time=20, is_billable=1
		)
		self.story_a = make_task(
			"HCR Sum Story A",
			"Story",
			self.epic_a.name,
			project=self.project.name,
			expected_time=10,
			is_billable=1,
		)
		self.task_a = make_task_under_story(self.story_a, "HCR Sum Task A", 5, is_billable=1)

		self.epic_b = make_task(
			"HCR Sum Epic B", "Epic", project=self.project.name, expected_time=8, is_billable=1
		)

		log_hours(self.employee, self.task_a.name, 4, today())

	def test_summary_counts_roots_only(self):
		_columns, data, _message, _chart, summary = execute({"project": self.project.name})
		labels = {card["label"]: card["value"] for card in summary}

		# Epic A, Story A and Task A each report 4 actual hours (the same hours,
		# rolled up). Summing every row would give 12.
		self.assertEqual(labels["Total Hours"], 4)
		self.assertEqual(labels["Billable Hours"], 4)
		self.assertEqual(labels["Non-Billable Hours"], 0)
		self.assertEqual(len(data), 4)

	def test_no_message_without_filters(self):
		_columns, _data, message, _chart, _summary = execute({"project": self.project.name})
		self.assertIsNone(message)

	def test_date_filter_produces_caveat_banner(self):
		_columns, _data, message, _chart, _summary = execute(
			{"project": self.project.name, "from_date": today(), "to_date": today()}
		)
		self.assertIn("Est Hours and Variance cover the whole engagement", message)

	def test_billable_only_produces_banner(self):
		_columns, _data, message, _chart, _summary = execute(
			{"project": self.project.name, "billable_only": 1}
		)
		self.assertIn("Non-billable work items are hidden", message)
