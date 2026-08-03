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


# The mirror of PARENT_SOURCES: (doctype, fieldname) pairs to search for
# dependants when something stops being billable.
DEPENDANT_SOURCES = {
	"Project": (("Task", "project"), ("Issue", "project")),
	"Issue": (("Task", "issue"),),
	"Task": (("Task", "parent_task"),),
}

# How many offenders to name before truncating the error message.
MAX_LISTED_DEPENDANTS = 10


def validate_no_billable_dependants(doc, method=None):
	# Only a real 1 -> 0 transition can strand a dependant. Anything else (a new
	# doc, an already-unbilled doc being saved again) costs one flag check.
	if cint(doc.get(BILLABLE_FIELD)) or doc.is_new():
		return

	before = doc.get_doc_before_save()
	if not before or not cint(before.get(BILLABLE_FIELD)):
		return

	dependants = []
	for child_doctype, fieldname in DEPENDANT_SOURCES.get(doc.doctype, ()):
		dependants += frappe.get_all(
			child_doctype, filters={fieldname: doc.name, BILLABLE_FIELD: 1}, pluck="name"
		)

	if doc.doctype == "Task":
		# Read the in-memory rows, not the DB: Frappe writes child rows AFTER
		# the parent's validate(), so the DB still shows the old values and a
		# save that unbills the Story and its rows together would throw.
		dependants += [row.task_item for row in doc.get("custom_task_split") or [] if cint(row.is_billable)]

	if not dependants:
		return

	listed = ", ".join(dependants[:MAX_LISTED_DEPENDANTS])
	if len(dependants) > MAX_LISTED_DEPENDANTS:
		listed += _(" and {0} more").format(len(dependants) - MAX_LISTED_DEPENDANTS)

	frappe.throw(
		_("Cannot turn off Billable while these are still billable: {0}. Unbill them first.").format(listed)
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
