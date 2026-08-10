import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from sigzenjira.sigzenjira.page.project_billing.project_billing import (
	BILLING_ROLES,
	get_bootstrap,
	get_project_billing,
	set_mark_as_read,
	update_billing_hours,
)
from sigzenjira.tests import ensure_test_employment_type
from sigzenjira.tests.test_billable import make_project, make_task

# See the note in test_billable.py on why IGNORE_TEST_RECORD_DEPENDENCIES is
# neither usable nor needed here: every fixture below is built by hand.


def make_employee(first_name):
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": first_name,
			"company": frappe.db.get_single_value("Global Defaults", "default_company"),
			"status": "Active",
			"gender": "Male",
			"date_of_birth": "1995-01-01",
			"date_of_joining": "2024-01-01",
			"employment_type": ensure_test_employment_type(),
		}
	).insert()


def make_submitted_timesheet(employee, task, project, hours, billing_hours=None, from_hour=9):
	# from_hour exists because core refuses two timesheets for one employee whose
	# hours overlap, so any test wanting a second sheet has to move it off 09:00.
	row = {
		"activity_type": "Execution",
		"task": task,
		"project": project,
		"from_time": f"{today()} {from_hour:02d}:00:00",
		"hours": hours,
	}
	if billing_hours is not None:
		row["billing_hours"] = billing_hours

	timesheet = frappe.get_doc({"doctype": "Timesheet", "employee": employee, "time_logs": [row]}).insert()
	timesheet.submit()
	return timesheet


class ProjectBillingCase(IntegrationTestCase):
	def setUp(self):
		# Administrator bypasses PROJECT_SCOPE_BYPASS_ROLES, which is what the
		# tests that are not about permissions want - the permission gates get
		# their own test below with a deliberately unprivileged user.
		frappe.set_user("Administrator")


class TestProjectBillingTree(ProjectBillingCase):
	def test_tree_nests_epic_story_task_and_the_timesheet_row(self):
		employee = make_employee("PB Tree Tester")
		project = make_project("PB Tree Project", is_billable=1)
		epic = make_task("PB Tree Epic", "Epic", project=project.name, is_billable=1)
		story = make_task("PB Tree Story", "Story", epic.name, project=project.name, is_billable=1)
		task = make_task("PB Tree Task", "Task", story.name, project=project.name, is_billable=1)

		make_submitted_timesheet(employee.name, task.name, project.name, hours=5, billing_hours=3)

		rows = get_project_billing(project.name)["rows"]
		shape = [(row["row_type"], row["indent"], row.get("work_item_type")) for row in rows]

		self.assertEqual(
			shape,
			[
				("task", 0, "Epic"),
				("task", 1, "Story"),
				("task", 2, "Task"),
				("timesheet", 3, None),
			],
		)

	def test_ancestor_rows_show_the_stored_rollup_not_just_their_own_rows(self):
		employee = make_employee("PB Rollup Tester")
		project = make_project("PB Rollup Project", is_billable=1)
		epic = make_task("PB Rollup Epic", "Epic", project=project.name, is_billable=1)
		story = make_task("PB Rollup Story", "Story", epic.name, project=project.name, is_billable=1)
		task = make_task("PB Rollup Task", "Task", story.name, project=project.name, is_billable=1)

		make_submitted_timesheet(employee.name, task.name, project.name, hours=8, billing_hours=6)

		rows = {row["label"]: row for row in get_project_billing(project.name)["rows"]}

		# The Epic logged nothing directly - these are its subtree's hours.
		self.assertEqual(rows["PB Rollup Epic"]["billing_hours"], 6)
		self.assertEqual(rows["PB Rollup Epic"]["non_billable_hours"], 2)

	def test_totals_cover_only_the_rows_in_view(self):
		employee = make_employee("PB Totals Tester")
		project = make_project("PB Totals Project", is_billable=1)
		task = make_task("PB Totals Task", "Task", project=project.name, is_billable=1)

		make_submitted_timesheet(employee.name, task.name, project.name, hours=4, billing_hours=1)

		data = get_project_billing(project.name)
		self.assertEqual(data["totals"]["hours"], 4)
		self.assertEqual(data["totals"]["billing_hours"], 1)
		self.assertEqual(data["totals"]["non_billable_hours"], 3)


class TestProjectBillingAdjust(ProjectBillingCase):
	def setup_project(self, name, hours=10, billing_hours=None):
		self.employee = make_employee(f"{name} Tester")
		self.project = make_project(name, is_billable=1)
		self.task = make_task(f"{name} Task", "Task", project=self.project.name, is_billable=1)
		self.timesheet = make_submitted_timesheet(
			self.employee.name, self.task.name, self.project.name, hours, billing_hours
		)
		return self.timesheet.time_logs[0]

	def test_adjusting_a_row_moves_the_row_task_and_project_together(self):
		row = self.setup_project("PB Adjust", hours=10)

		update_billing_hours([{"name": row.name, "billing_hours": 4}])

		detail = frappe.db.get_value(
			"Timesheet Detail",
			row.name,
			["billing_hours", "custom_timesheet_detail_non_billable_hours"],
			as_dict=True,
		)
		self.assertEqual(detail.billing_hours, 4)
		self.assertEqual(detail.custom_timesheet_detail_non_billable_hours, 6)

		self.assertEqual(frappe.db.get_value("Task", self.task.name, "custom_task_billable_hours"), 4)
		self.assertEqual(frappe.db.get_value("Task", self.task.name, "custom_task_non_billable_hours"), 6)

		self.assertEqual(
			frappe.db.get_value("Project", self.project.name, "custom_project_billable_hours"), 4
		)
		self.assertEqual(
			frappe.db.get_value("Project", self.project.name, "custom_project_non_billable_hours"), 6
		)

	def test_adjusting_a_row_refreshes_the_parent_timesheets_totals(self):
		# Core's Timesheet.on_update_after_submit never calls
		# calculate_total_amounts, so without _apply_to_timesheet doing it the
		# parent would still claim the pre-edit figure.
		row = self.setup_project("PB Totals Refresh", hours=10)

		update_billing_hours([{"name": row.name, "billing_hours": 2}])

		self.assertEqual(
			frappe.db.get_value("Timesheet", self.timesheet.name, "total_billable_hours"), 2
		)

	def test_billing_amount_follows_the_new_hours(self):
		row = self.setup_project("PB Amount", hours=10)
		frappe.db.set_value("Timesheet Detail", row.name, "billing_rate", 100, update_modified=False)

		update_billing_hours([{"name": row.name, "billing_hours": 3}])

		self.assertEqual(frappe.db.get_value("Timesheet Detail", row.name, "billing_amount"), 300)

	def test_billable_hours_above_hours_worked_is_refused(self):
		row = self.setup_project("PB Over", hours=6)

		with self.assertRaises(frappe.ValidationError) as caught:
			update_billing_hours([{"name": row.name, "billing_hours": 9}])
		self.assertIn("cannot exceed", str(caught.exception))

	def test_negative_billable_hours_is_refused(self):
		row = self.setup_project("PB Negative", hours=6)

		with self.assertRaises(frappe.ValidationError) as caught:
			update_billing_hours([{"name": row.name, "billing_hours": -1}])
		self.assertIn("cannot be negative", str(caught.exception))

	def test_a_non_billable_row_cannot_be_given_billable_hours(self):
		employee = make_employee("PB Free Tester")
		project = make_project("PB Free Project", is_billable=1)
		task = make_task("PB Free Task", "Task", project=project.name, is_billable=0)
		timesheet = make_submitted_timesheet(employee.name, task.name, project.name, hours=5)

		with self.assertRaises(frappe.ValidationError) as caught:
			update_billing_hours([{"name": timesheet.time_logs[0].name, "billing_hours": 2}])
		self.assertIn("not billable", str(caught.exception))

	def test_an_invoiced_row_is_frozen(self):
		row = self.setup_project("PB Invoiced", hours=8)
		frappe.db.set_value("Timesheet Detail", row.name, "sales_invoice", "SINV-FAKE", update_modified=False)

		with self.assertRaises(frappe.ValidationError) as caught:
			update_billing_hours([{"name": row.name, "billing_hours": 2}])
		self.assertIn("already invoiced", str(caught.exception))

	def test_the_adjustment_leaves_a_comment_on_the_timesheet(self):
		# db.set_value writes no version history, so this comment is the only
		# record of who moved a billed figure and from what.
		row = self.setup_project("PB Trail", hours=10)

		update_billing_hours([{"name": row.name, "billing_hours": 7}])

		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Timesheet", "reference_name": self.timesheet.name},
			pluck="content",
		)
		self.assertTrue(any("Billable hours adjusted" in (c or "") for c in comments))

	def test_setting_billable_hours_to_zero_sticks(self):
		# Core refills billing_hours from hours whenever it finds 0
		# (timesheet_detail.py:update_billing_hours), but that runs on validate -
		# the page writes with db.set_value, so 0 survives here.
		row = self.setup_project("PB Zero", hours=5)

		update_billing_hours([{"name": row.name, "billing_hours": 0}])

		self.assertEqual(frappe.db.get_value("Timesheet Detail", row.name, "billing_hours"), 0)
		self.assertEqual(
			frappe.db.get_value(
				"Timesheet Detail", row.name, "custom_timesheet_detail_non_billable_hours"
			),
			5,
		)


class TestProjectBillingMarkAsRead(ProjectBillingCase):
	def test_mark_as_read_round_trips(self):
		employee = make_employee("PB Read Tester")
		project = make_project("PB Read Project", is_billable=1)
		task = make_task("PB Read Task", "Task", project=project.name, is_billable=1)
		timesheet = make_submitted_timesheet(employee.name, task.name, project.name, hours=3)
		row_name = timesheet.time_logs[0].name

		set_mark_as_read([row_name], 1)
		rows = get_project_billing(project.name)["rows"]
		detail = next(row for row in rows if row["row_type"] == "timesheet")
		self.assertEqual(detail["mark_as_read"], 1)

		set_mark_as_read([row_name], 0)
		self.assertEqual(
			frappe.db.get_value("Timesheet Detail", row_name, "custom_timesheet_detail_mark_as_read"), 0
		)


class TestProjectBillingIsUpdatedFilter(ProjectBillingCase):
	def setup_two_rows(self, name):
		employee = make_employee(f"{name} Tester")
		self.project = make_project(name, is_billable=1)
		self.task = make_task(f"{name} Task", "Task", project=self.project.name, is_billable=1)

		self.read = make_submitted_timesheet(employee.name, self.task.name, self.project.name, hours=2)
		self.unread = make_submitted_timesheet(
			employee.name, self.task.name, self.project.name, hours=3, from_hour=14
		)
		set_mark_as_read([self.read.time_logs[0].name], 1)

	def detail_names(self, **filters):
		rows = get_project_billing(self.project.name, **filters)["rows"]
		return {row["name"] for row in rows if row["row_type"] == "timesheet"}

	def test_off_hides_the_rows_already_ticked_as_read(self):
		self.setup_two_rows("PB Unread Only")

		self.assertEqual(self.detail_names(is_updated=0), {self.unread.time_logs[0].name})

	def test_on_shows_only_the_rows_ticked_as_read(self):
		self.setup_two_rows("PB Read Only")

		self.assertEqual(self.detail_names(is_updated=1), {self.read.time_logs[0].name})

	def test_the_filter_does_not_narrow_the_employee_dropdown(self):
		# Built before the filter runs, so somebody whose every row is read stays
		# selectable rather than vanishing from a list they belong on.
		self.setup_two_rows("PB Read Dropdown")

		data = get_project_billing(self.project.name, is_updated=1)
		self.assertEqual(len(data["employees"]), 1)

	def test_omitting_the_filter_shows_both(self):
		self.setup_two_rows("PB Read Unfiltered")

		self.assertEqual(
			self.detail_names(), {self.read.time_logs[0].name, self.unread.time_logs[0].name}
		)


class TestProjectBillingDetailColumns(ProjectBillingCase):
	def test_a_timesheet_row_carries_what_the_table_columns_show(self):
		employee = make_employee("PB Columns Tester")
		project = make_project("PB Columns Project", is_billable=1)
		task = make_task("PB Columns Task", "Task", project=project.name, is_billable=1)

		timesheet = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"employee": employee.name,
				"time_logs": [
					{
						"activity_type": "Execution",
						"description": "Rebuilt the importer",
						"task": task.name,
						"project": project.name,
						"from_time": f"{today()} 09:00:00",
						"hours": 4,
					}
				],
			}
		).insert()
		timesheet.submit()

		rows = get_project_billing(project.name)["rows"]
		detail = next(row for row in rows if row["row_type"] == "timesheet")

		self.assertEqual(detail["activity_type"], "Execution")
		self.assertIn("Rebuilt the importer", detail["description"])
		self.assertEqual(detail["timesheet"], timesheet.name)


class TestProjectBillingPermissions(ProjectBillingCase):
	def make_unprivileged_user(self):
		user = "pb.unprivileged@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": "PB Unprivileged",
					"send_welcome_email": 0,
					"roles": [{"role": "Projects User"}],
				}
			).insert(ignore_permissions=True)
		return user

	def test_a_projects_user_cannot_adjust_billable_hours(self):
		employee = make_employee("PB Perm Tester")
		project = make_project("PB Perm Project", is_billable=1)
		task = make_task("PB Perm Task", "Task", project=project.name, is_billable=1)
		timesheet = make_submitted_timesheet(employee.name, task.name, project.name, hours=5)

		user = self.make_unprivileged_user()
		# Submitting the timesheet writes back to the Project (core's
		# update_task_and_project), so the copy captured before that is stale and
		# saving it would trip TimestampMismatchError.
		project.reload()
		project.append("users", {"user": user})
		project.save(ignore_permissions=True)

		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				update_billing_hours([{"name": timesheet.time_logs[0].name, "billing_hours": 2}])
		finally:
			frappe.set_user("Administrator")

	def test_a_projects_user_cannot_even_read_a_project_they_are_a_member_of(self):
		# Membership is not the gate here, the role is: BILLING_ROLES is one gate
		# for reading and adjusting alike, so a Projects User is refused on a
		# project they legitimately work on.
		project = make_project("PB Member Project", is_billable=1)
		user = self.make_unprivileged_user()
		project.append("users", {"user": user})
		project.save(ignore_permissions=True)

		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_project_billing(project.name)
		finally:
			frappe.set_user("Administrator")

	def test_a_projects_user_cannot_list_the_billable_projects(self):
		user = self.make_unprivileged_user()

		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_bootstrap()
		finally:
			frappe.set_user("Administrator")

	def test_a_projects_user_cannot_tick_a_row_as_read(self):
		employee = make_employee("PB Read Perm Tester")
		project = make_project("PB Read Perm Project", is_billable=1)
		task = make_task("PB Read Perm Task", "Task", project=project.name, is_billable=1)
		timesheet = make_submitted_timesheet(employee.name, task.name, project.name, hours=2)

		user = self.make_unprivileged_user()
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				set_mark_as_read([timesheet.time_logs[0].name], 1)
		finally:
			frappe.set_user("Administrator")

	def test_the_page_role_list_matches_the_server_gate(self):
		# frappe's Page.is_permitted is a plain role intersection with no System
		# Manager bypass, so project_billing.json is a separate gate from
		# BILLING_ROLES. A role added to one and not the other is either a page
		# nobody can open or a method nobody can reach.
		page_roles = set(
			frappe.get_all("Has Role", filters={"parent": "project-billing", "parenttype": "Page"}, pluck="role")
		)
		self.assertEqual(page_roles, BILLING_ROLES)


class TestProjectBillingWorkItemTypeFilter(ProjectBillingCase):
	def setup_hierarchy(self, name):
		self.employee = make_employee(f"{name} Tester")
		self.project = make_project(name, is_billable=1)
		self.epic = make_task(f"{name} Epic", "Epic", project=self.project.name, is_billable=1)
		self.story = make_task(f"{name} Story", "Story", self.epic.name, project=self.project.name, is_billable=1)
		self.task = make_task(f"{name} Task", "Task", self.story.name, project=self.project.name, is_billable=1)

	def test_picking_story_reroots_the_tree_and_keeps_the_subtree(self):
		self.setup_hierarchy("PB Reroot")
		make_submitted_timesheet(self.employee.name, self.task.name, self.project.name, hours=5, billing_hours=3)

		rows = get_project_billing(self.project.name, work_item_type="Story")["rows"]

		self.assertEqual(
			[(row["row_type"], row["indent"], row.get("work_item_type")) for row in rows],
			[("task", 0, "Story"), ("task", 1, "Task"), ("timesheet", 2, None)],
		)

	def test_a_work_item_with_no_hours_below_it_is_dropped(self):
		# The Epic here has a whole subtree and not one submitted hour in it.
		self.setup_hierarchy("PB Empty Branch")

		self.assertEqual(get_project_billing(self.project.name)["rows"], [])

	def test_the_no_task_bucket_is_out_of_view_under_a_type_filter(self):
		self.setup_hierarchy("PB Loose Under Filter")
		make_submitted_timesheet(self.employee.name, self.task.name, self.project.name, hours=5, billing_hours=5)

		loose = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"employee": self.employee.name,
				"time_logs": [
					{
						"activity_type": "Execution",
						"project": self.project.name,
						"from_time": f"{today()} 14:00:00",
						"hours": 2,
						"is_billable": 1,
					}
				],
			}
		).insert()
		loose.submit()

		unfiltered = get_project_billing(self.project.name)
		filtered = get_project_billing(self.project.name, work_item_type="Story")

		# It belongs to no work item, so it is in view only without a type filter -
		# and the totals move with it rather than counting rows nobody can see.
		self.assertTrue(any(row["row_type"] == "task" and not row["name"] for row in unfiltered["rows"]))
		self.assertFalse(any(row["row_type"] == "task" and not row["name"] for row in filtered["rows"]))
		self.assertEqual(unfiltered["totals"]["hours"], 7)
		self.assertEqual(filtered["totals"]["hours"], 5)


class TestProjectBillingEmployeeFilter(ProjectBillingCase):
	def setup_two_loggers(self, name):
		self.one = make_employee(f"{name} One")
		self.two = make_employee(f"{name} Two")
		self.project = make_project(name, is_billable=1)
		self.task = make_task(f"{name} Task", "Task", project=self.project.name, is_billable=1)

		make_submitted_timesheet(self.one.name, self.task.name, self.project.name, hours=4, billing_hours=4)
		make_submitted_timesheet(self.two.name, self.task.name, self.project.name, hours=6, billing_hours=6)

	def test_the_employee_list_is_everyone_who_billed_the_project(self):
		self.setup_two_loggers("PB Emp List")

		names = {row["name"] for row in get_project_billing(self.project.name)["employees"]}

		self.assertEqual(names, {self.one.name, self.two.name})

	def test_a_project_user_who_never_logged_time_is_still_offered(self):
		self.setup_two_loggers("PB Emp Idle")
		email = "pb-emp-idle-three@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "PB Idle", "send_welcome_email": 0}
			).insert(ignore_permissions=True)

		idle = make_employee("PB Emp Idle Three")
		idle.db_set("user_id", email)
		# Submitting the timesheets wrote back to the Project, so the copy from
		# setup is stale and saving it would trip TimestampMismatchError.
		self.project.reload()
		self.project.append("users", {"user": email})
		self.project.save(ignore_permissions=True)

		names = {row["name"] for row in get_project_billing(self.project.name)["employees"]}

		self.assertEqual(names, {self.one.name, self.two.name, idle.name})

	def test_filtering_by_employee_keeps_only_their_timesheet_rows(self):
		self.setup_two_loggers("PB Emp Filter")

		data = get_project_billing(self.project.name, employee=self.one.name)
		details = [row for row in data["rows"] if row["row_type"] == "timesheet"]

		self.assertEqual([row["employee"] for row in details], [self.one.name])
		self.assertEqual(data["totals"]["hours"], 4)

	def test_filtering_by_employee_still_offers_every_other_logger(self):
		# The dropdown is built before the filter is applied, so picking someone
		# must not strand the user with a list of one.
		self.setup_two_loggers("PB Emp Keep")

		data = get_project_billing(self.project.name, employee=self.one.name)

		self.assertEqual(
			{row["name"] for row in data["employees"]}, {self.one.name, self.two.name}
		)


class TestProjectBillingUnassignedTime(ProjectBillingCase):
	def test_time_logged_without_a_task_still_appears(self):
		# recompute_project_billable_hours counts it, so the page has to show it
		# or the project total on screen would not add up.
		employee = make_employee("PB Loose Tester")
		project = make_project("PB Loose Project", is_billable=1)

		timesheet = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"employee": employee.name,
				"time_logs": [
					{
						"activity_type": "Execution",
						"project": project.name,
						"from_time": f"{today()} 09:00:00",
						"hours": 3,
						"is_billable": 1,
					}
				],
			}
		).insert()
		timesheet.submit()

		rows = get_project_billing(project.name)["rows"]
		bucket = [row for row in rows if row["row_type"] == "task" and not row["name"]]

		self.assertEqual(len(bucket), 1)
		self.assertEqual(flt(bucket[0]["hours"]), 3)
