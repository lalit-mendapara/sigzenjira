import frappe
from frappe.tests import IntegrationTestCase

EMPLOYEE_USER = "test_story_template_employee@example.com"


def ensure_employee_user():
	if not frappe.db.exists("User", EMPLOYEE_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": EMPLOYEE_USER,
				"first_name": "Story Template Employee",
				"send_welcome_email": 0,
				"roles": [{"role": "Employee"}, {"role": "Projects User"}],
			}
		).insert(ignore_permissions=True)
	return EMPLOYEE_USER


def make_story(subject="ESR Story", epic=None):
	story = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_task_work_item_type": "Story",
			"parent_task": epic.name if epic else None,
		}
	)
	story.insert()
	return story


def make_task_template():
	if frappe.db.exists("Task Template", "ESR Checklist"):
		return frappe.get_doc("Task Template", "ESR Checklist")
	return frappe.get_doc(
		{
			"doctype": "Task Template",
			"name": "ESR Checklist",
			"tasks": [{"task_item": "Design", "description": "Design step"}],
		}
	).insert()


class TestEmployeeStoryTemplateRestriction(IntegrationTestCase):
	def test_employee_can_select_template_and_save(self):
		user = ensure_employee_user()
		story = make_story("ESR Template Select")
		template = make_task_template()

		frappe.set_user(user)
		try:
			story_as_employee = frappe.get_doc("Task", story.name)
			story_as_employee.custom_task_task_template = template.name
			story_as_employee.append("custom_task_task_split", {"task_item": "Design", "description": "Design step"})
			story_as_employee.save()
		finally:
			frappe.set_user("Administrator")

		story.reload()
		self.assertEqual(story.custom_task_task_template, template.name)
		self.assertEqual(len(story.custom_task_task_split), 1)

	def test_employee_cannot_edit_other_fields(self):
		user = ensure_employee_user()
		story = make_story("ESR Other Field")

		frappe.set_user(user)
		try:
			story_as_employee = frappe.get_doc("Task", story.name)
			story_as_employee.subject = "Changed by employee"
			with self.assertRaises(frappe.ValidationError):
				story_as_employee.save()
		finally:
			frappe.set_user("Administrator")

	def test_employee_cannot_add_split_row_with_hours(self):
		user = ensure_employee_user()
		story = make_story("ESR Hours Row")

		frappe.set_user(user)
		try:
			story_as_employee = frappe.get_doc("Task", story.name)
			story_as_employee.append("custom_task_task_split", {"task_item": "Real work", "expected_hours": 5})
			with self.assertRaises(frappe.ValidationError):
				story_as_employee.save()
		finally:
			frappe.set_user("Administrator")

	def test_employee_cannot_delete_split_row(self):
		user = ensure_employee_user()
		story = make_story("ESR Row Delete")
		story.append("custom_task_task_split", {"task_item": "Design", "description": "Design step"})
		story.save()

		frappe.set_user(user)
		try:
			story_as_employee = frappe.get_doc("Task", story.name)
			story_as_employee.custom_task_task_split = []
			with self.assertRaises(frappe.ValidationError):
				story_as_employee.save()
		finally:
			frappe.set_user("Administrator")

		story.reload()
		self.assertEqual(len(story.custom_task_task_split), 1)

	def test_privileged_role_can_delete_split_row(self):
		story = make_story("ESR Row Delete Privileged")
		story.append("custom_task_task_split", {"task_item": "Design", "description": "Design step"})
		story.save()

		story.custom_task_task_split = []
		story.save()

		story.reload()
		self.assertEqual(len(story.custom_task_task_split), 0)

	def test_employee_has_read_only_access_to_task_template(self):
		user = ensure_employee_user()
		template = make_task_template()

		frappe.set_user(user)
		try:
			self.assertTrue(frappe.has_permission("Task Template", "read", doc=template.name))
			self.assertFalse(frappe.has_permission("Task Template", "create"))
		finally:
			frappe.set_user("Administrator")

	def test_privileged_role_unaffected(self):
		story = make_story("ESR Privileged Edit")
		story.subject = "Changed by PM"
		story.save()
		self.assertEqual(frappe.db.get_value("Task", story.name, "subject"), "Changed by PM")
