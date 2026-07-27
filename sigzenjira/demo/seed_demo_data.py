# Run once before a demo:
#   bench --site mysite.in execute sigzenjira.demo.seed_demo_data.run
# Idempotent - re-running skips anything that already exists, so it's safe
# to run again before a repeat demo.

import frappe
from frappe.utils import flt

COMPANY = None  # picked up from Global Defaults at run time

DEVELOPER_USER = "demo.developer@sigzenjira.demo"
PM_USER = "demo.pm@sigzenjira.demo"
DEMO_PASSWORD = "Demo@1234"


def run():
	global COMPANY
	COMPANY = frappe.db.get_single_value("Global Defaults", "default_company")
	if not COMPANY:
		frappe.throw("Set a default Company in Global Defaults before seeding demo data.")

	frappe.set_user("Administrator")

	developer = make_user(DEVELOPER_USER, "Dev Developer", ["Employee", "Projects User"])
	pm = make_user(PM_USER, "Priya Manager", ["Projects Manager"])
	make_employee(developer)

	epic = make_task("Website Revamp", "Epic", expected_time=40)
	story1 = make_task("Checkout Flow", "Story", epic.name, expected_time=16)
	story2 = make_task("Search & Filters", "Story", epic.name, expected_time=12)

	t1 = make_task("Cart page redesign", "Task", story1.name, expected_time=6, assigned=developer)
	t2 = make_task("Payment gateway integration", "Task", story1.name, expected_time=10, assigned=developer)

	t3 = make_task("Filter sidebar UI", "Task", story2.name, expected_time=5, assigned=developer)
	make_task("Search relevance tuning", "Task", story2.name, expected_time=7, assigned=developer)

	make_task("Write unit tests for cart", "Sub-task", t1.name)
	make_task("Fix mobile cart layout bug", "Sub-task", t1.name)

	# One already-approved request, so the demo can show a Task/Story/Epic
	# that already carries rolled-up Extra Hours without any live clicking.
	approved = make_ahr(
		t2.name,
		developer,
		4,
		"Payment gateway vendor added 3-D Secure late in the sprint, needs extra dev time.",
	)
	if approved.status == "Draft":
		approve_ahr(approved, pm)

	# One left in Pending, for the PM user to Approve/Reject live during the demo.
	pending = make_ahr(
		t3.name,
		developer,
		3,
		"Design added a saved-filters panel after estimation was locked.",
	)
	if pending.status == "Draft":
		from frappe.model.workflow import apply_workflow

		frappe.set_user(developer)
		apply_workflow(pending.as_dict(), "Submit")
		frappe.set_user("Administrator")

	frappe.db.commit()

	print("Demo data ready.")
	print(f"  Developer login: {DEVELOPER_USER} / {DEMO_PASSWORD}")
	print(f"  PM login:        {PM_USER} / {DEMO_PASSWORD}")
	print(f"  Epic: {epic.name}  Story-1: {story1.name}  Story-2: {story2.name}")
	print(f"  Task with approved AHR (extra_hours=4): {t2.name}")
	print(f"  Task with a Pending AHR to approve live: {t3.name}")


def make_user(email, full_name, roles):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": full_name.split()[0],
				"last_name": " ".join(full_name.split()[1:]),
				"send_welcome_email": 0,
				"new_password": DEMO_PASSWORD,
			}
		)
		user.insert(ignore_permissions=True)

	existing_roles = {r.role for r in user.roles}
	for role in roles:
		if role not in existing_roles:
			user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	return user.name


def make_employee(user):
	existing = frappe.db.get_value("Employee", {"user_id": user})
	if existing:
		return existing

	full_name = frappe.db.get_value("User", user, "full_name")
	employee = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": full_name,
			"user_id": user,
			"company": COMPANY,
			"status": "Active",
			"gender": "Male",
			"date_of_birth": "1995-01-01",
			"date_of_joining": "2024-01-01",
		}
	)
	employee.insert(ignore_permissions=True)
	return employee.name


def make_task(subject, work_item_type, parent_task=None, expected_time=0, assigned=None):
	existing = frappe.db.get_value("Task", {"subject": subject, "custom_work_item_type": work_item_type})
	if existing:
		return frappe.get_doc("Task", existing)

	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"custom_work_item_type": work_item_type,
			"parent_task": parent_task,
			"expected_time": expected_time,
		}
	)
	doc.insert(ignore_permissions=True)

	if assigned:
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"reference_type": "Task",
				"reference_name": doc.name,
				"allocated_to": assigned,
				"description": f"Work on: {subject}",
			}
		).insert(ignore_permissions=True)

	return doc


def make_ahr(task_name, requested_by, hours, reason):
	existing = frappe.db.get_value(
		"Additional Hours Request", {"task": task_name, "additional_hours_requested": hours, "reason": reason}
	)
	if existing:
		return frappe.get_doc("Additional Hours Request", existing)

	doc = frappe.get_doc(
		{
			"doctype": "Additional Hours Request",
			"task": task_name,
			"requested_by": requested_by,
			"additional_hours_requested": hours,
			"reason": reason,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def approve_ahr(doc, approver):
	from frappe.model.workflow import apply_workflow

	frappe.set_user(doc.requested_by)
	apply_workflow(doc.as_dict(), "Submit")
	frappe.set_user(approver)
	doc.reload()
	apply_workflow(doc.as_dict(), "Approve")
	frappe.set_user("Administrator")
