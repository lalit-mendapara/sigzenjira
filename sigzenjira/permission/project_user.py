import frappe

PROJECT_USER_BYPASS_ROLES = {"System Manager"}


def user_has_project_flag(project, fieldname, user=None):
	user = user or frappe.session.user
	if user == "Administrator" or PROJECT_USER_BYPASS_ROLES & set(frappe.get_roles(user)):
		return True
	if not project:
		return False
	return bool(
		frappe.db.exists(
			"Project User",
			{"parenttype": "Project", "parentfield": "users", "parent": project, "user": user, fieldname: 1},
		)
	)


def get_project_approvers(project):
	if not project:
		return []
	return frappe.get_all(
		"Project User",
		filters={
			"parenttype": "Project",
			"parentfield": "users",
			"parent": project,
			"custom_project_user_approve_extra_hours": 1,
		},
		pluck="user",
	)


def ecd_alert_manager_emails(project):
	# Jinja-facing wrapper for the "Task ECD Due" / "Issue ECD Due" Notification
	# cc field, which is rendered as a template and then split on commas. Reuses
	# get_project_approvers so "manager on this project" has one definition -
	# change the flag there and the AHR routing and this alert both follow.
	# A User docname is the email address, so no lookup is needed.
	return ",".join(get_project_approvers(project))
