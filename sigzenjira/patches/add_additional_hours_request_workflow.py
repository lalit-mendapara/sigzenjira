from sigzenjira.setup import create_additional_hours_request_workflow


def execute():
	# Workflow only. create_task_projects_manager_docperm() used to run here too,
	# but every Custom DocPerm row it writes is covered by the Custom DocPerm
	# fixture (parent in Task / Task Template) and re-applied force=True on every
	# migrate. Workflow is not a fixture, so this half still needs a patch.
	create_additional_hours_request_workflow()
