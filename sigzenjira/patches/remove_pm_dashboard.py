import json

import frappe

# Names are frozen here rather than imported: dashboard/pm_dashboard.py is
# deleted along with the feature this patch removes.
DASHBOARD = "Project Management Dashboard"
SHORTCUT_BLOCK_ID = "sigzenjiraPmDashboardShortcut"

NUMBER_CARDS = [
	"Open Tasks",
	"Task Overdue Count",
	"Pending Extra Hours Approvals",
	"Extra Hours Approved",
	"Hours Logged This Week",
	"Open Issues",
	"My Open Tasks",
	"My Overdue Tasks",
	"My Hours This Week",
	"My Pending Extra Hours Requests",
	"My Approved Extra Hours",
	"My Open Issues",
]

CHARTS = [
	"Tasks by Status",
	"Tasks by Work Item Type Breakdown",
	"Issues by Status",
	"Workload Distribution",
	"Hours Logged Trend",
	"My Tasks by Status",
	"My Issues by Status",
	"My Hours Trend",
]

REPORTS = [
	"Open Tasks Count",
	"Overdue Tasks Count",
	"Pending Extra Hours Count",
	"Extra Hours Approved Sum",
	"Hours This Week Sum",
	"Open Issues Count",
]


def execute():
	remove_workspace_shortcut()

	# Order matters: the Dashboard links the cards and charts, and each
	# manager-side Number Card links its backing Report.
	for doctype, names in (
		("Dashboard", [DASHBOARD]),
		("Number Card", NUMBER_CARDS),
		("Dashboard Chart", CHARTS),
		("Report", REPORTS),
	):
		for name in names:
			frappe.delete_doc(
				doctype,
				name,
				ignore_permissions=True,
				ignore_missing=True,
				force=True,
				delete_permanently=True,
			)


def remove_workspace_shortcut():
	# Same LinkValidationError landmine the creating code documented: the
	# "Project Management" workspace carries a pre-existing broken shortcut, so
	# ws.save() would crash. Touch the child row and `content` directly.
	frappe.db.delete("Workspace Shortcut", {"parent": "Project Management", "link_to": DASHBOARD})

	content = json.loads(frappe.db.get_value("Workspace", "Project Management", "content") or "[]")
	kept = [block for block in content if block.get("id") != SHORTCUT_BLOCK_ID]
	if len(kept) != len(content):
		frappe.db.set_value("Workspace", "Project Management", "content", json.dumps(kept))
