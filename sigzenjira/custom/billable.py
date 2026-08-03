import frappe
from frappe import _
from frappe.utils import cint, get_link_to_form

BILLABLE_FIELD = "custom_is_billable"

# Every parent a doc declares. A billable claim must hold against ALL of them,
# not just the nearest - make_story() creates a STANDALONE Story (no
# parent_task), so a nearest-source rule would resolve to the still-billable
# Project and let a deliberately-unbilled support Story be flipped back to
# billable, silently overriding the Issue. Costs nothing in the ordinary case:
# an Issue is itself clamped against its Project and a parent chain is clamped
# all the way up, so the extra checks are already satisfied by transitivity.
PARENT_SOURCES = {
	"Task": (("Task", "parent_task"), ("Issue", "issue"), ("Project", "project")),
	"Issue": (("Project", "project"),),
	"Project": (),
}


def validate_billable_under_billable_parent(doc, method=None):
	if not cint(doc.get(BILLABLE_FIELD)):
		return

	for parent_doctype, fieldname in PARENT_SOURCES.get(doc.doctype, ()):
		parent = doc.get(fieldname)
		if not parent:
			continue
		if not cint(frappe.db.get_value(parent_doctype, parent, BILLABLE_FIELD)):
			frappe.throw(
				_("{0} {1} is not billable, so this {2} cannot be billable.").format(
					parent_doctype, get_link_to_form(parent_doctype, parent), doc.doctype
				)
			)


def validate_task_split_billable(doc, method=None):
	# The split rows live on the Story, so their "parent" for clamp purposes is
	# the Story itself - checked here rather than in PARENT_SOURCES because a
	# child row is not a doc with its own validate().
	if doc.custom_work_item_type != "Story" or cint(doc.get(BILLABLE_FIELD)):
		return

	for row in doc.get("custom_task_split") or []:
		if cint(row.is_billable):
			frappe.throw(
				_("Row {0} ({1}) is marked Billable, but this Story is not.").format(row.idx, row.task_item)
			)
