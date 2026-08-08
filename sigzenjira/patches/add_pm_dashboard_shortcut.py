from sigzenjira.dashboard.pm_dashboard import add_pm_dashboard_workspace_shortcut


def execute():
	# Only the Workspace half. The Report / Number Card / Dashboard Chart /
	# Dashboard rows this used to create are all `fixtures` (hooks.py) and are
	# re-applied force=True on every migrate - creating them here too was dead
	# weight. Workspace is not a fixture, so the shortcut + content block still
	# needs a patch to reach an already-installed site.
	add_pm_dashboard_workspace_shortcut()
