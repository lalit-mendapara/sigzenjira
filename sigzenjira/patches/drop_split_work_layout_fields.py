import frappe

# Layout-only fields from the old Split Work arrangement. Issue ECD now sits at
# the top of the Split Work tab, above Task Template, so the column break that
# put it beside Task Template - and the section break that un-squeezed the grid
# after it - have nothing left to do. The stale "Split Work" section break in
# the first tab was orphaned when the Split Work tab replaced it.
FIELDS = (
	"Task-custom_task_split_work_cb",
	"Task-custom_task_task_split_section",
	"Task-custom_task_split_work_section",
)


def execute():
	for name in FIELDS:
		frappe.delete_doc("Custom Field", name, ignore_missing=True, force=True)
