import frappe

# Roles that see across every project - the approval/oversight layer. Everyone
# else is scoped to the Projects they are actually a Project User on.
# Kept in step with MANAGER_ROLES in sigzenjira/work_board.py on purpose: a role
# that gets every project's board would otherwise open a Task from it and be
# refused by this hook.
PROJECT_SCOPE_BYPASS_ROLES = {"Director", "Product Owner", "Projects Manager", "System Manager"}


def _bypasses_project_scope(user):
	return user == "Administrator" or bool(PROJECT_SCOPE_BYPASS_ROLES & set(frappe.get_roles(user)))


def user_is_project_member(project, user=None):
	user = user or frappe.session.user
	if _bypasses_project_scope(user):
		return True
	if not project:
		# A Task with no Project belongs to no team, so scoping it out would
		# hide standalone work from everyone but a manager - the plain role
		# permission stays the only gate on it.
		return True
	return bool(
		frappe.db.exists(
			"Project User",
			{"parenttype": "Project", "parentfield": "users", "parent": project, "user": user},
		)
	)


def _member_projects_subquery(user):
	return f"""select pu.parent from `tabProject User` pu
		where pu.parenttype = 'Project' and pu.parentfield = 'users'
		and pu.user = {frappe.db.escape(user)}"""


def task_query_conditions(user=None):
	user = user or frappe.session.user
	if _bypasses_project_scope(user):
		return ""
	return f"""(
		ifnull(`tabTask`.project, '') = ''
		or `tabTask`.project in ({_member_projects_subquery(user)})
	)"""


def task_has_permission(doc, ptype=None, user=None, **kwargs):
	# The kwarg MUST be named `ptype` - frappe.call() matches hook arguments
	# against the signature and silently drops anything that doesn't match
	# (see has_controller_permissions in frappe/permissions.py), so a
	# `permission_type` parameter would just sit at None forever.
	#
	# A hook returning None reads as DENY in this frappe version, so every
	# allowed path returns True explicitly.
	return user_is_project_member(doc.get("project"), user or frappe.session.user)


def project_query_conditions(user=None):
	user = user or frappe.session.user
	if _bypasses_project_scope(user):
		return ""
	# The creator keeps their own Project even before adding themselves to the
	# users table - otherwise a fresh Project disappears the moment it saves.
	return f"""(
		`tabProject`.owner = {frappe.db.escape(user)}
		or `tabProject`.name in ({_member_projects_subquery(user)})
	)"""


def project_has_permission(doc, ptype=None, user=None, **kwargs):
	user = user or frappe.session.user
	if _bypasses_project_scope(user):
		return True
	# An unsaved Project has no name to look up and no owner yet - defer to the
	# role-level create permission rather than denying every new Project.
	if not doc.get("creation"):
		return True
	if doc.get("owner") == user:
		return True
	return user_is_project_member(doc.get("name"), user)
