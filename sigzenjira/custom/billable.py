import frappe
from frappe import _
from frappe.utils import cint, get_link_to_form

from sigzenjira.custom.task import WORK_ITEM_TYPE_PRIVILEGED_ROLES

BILLABLE_FIELD = "custom_is_billable"

# --- Permission gate: only privileged roles may change Billable ---


def validate_billable_edit_permission(doc, method=None):
	# Billable is a money decision. Compared against the previous saved value
	# rather than blanket-blocked, so an Employee can still save unrelated edits
	# (status, progress) on a billable item without tripping this.
	if doc.flags.ignore_permissions or doc.flags.via_issue_mapping or doc.flags.via_split_generation:
		# Set by our own server-side propagation (generate_tasks_from_split
		# inserts with ignore_permissions=True; make_story sets via_issue_mapping;
		# create_task_without_hours sets via_split_generation) - the value was
		# copied from an already-validated parent, not chosen by whoever
		# happened to trigger the save.
		return

	if WORK_ITEM_TYPE_PRIVILEGED_ROLES & set(frappe.get_roles(frappe.session.user)):
		return

	before = doc.get_doc_before_save()
	previous = 0 if doc.is_new() else cint((before or {}).get(BILLABLE_FIELD))
	if cint(doc.get(BILLABLE_FIELD)) != previous:
		frappe.throw(_("Only a Director, Product Owner, or Projects Manager can change Billable."))

	if doc.doctype != "Task" or doc.custom_work_item_type != "Story":
		return

	before_rows = {row.name: cint(row.is_billable) for row in (before.custom_task_split if before else [])}
	for row in doc.get("custom_task_split") or []:
		if cint(row.is_billable) != before_rows.get(row.name, 0):
			frappe.throw(
				_(
					"Only a Director, Product Owner, or Projects Manager can change Billable on the Task Split table."
				)
			)


# --- Upward clamp: billable only under billable ---

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


# --- Downward clamp: no billable dependants left behind ---

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

	# No split-row leg here on purpose: validate_task_split_billable runs
	# earlier in the Task validate list and is strictly broader (it fires on
	# any save where a Story's flag is off and a row's is on, not only on a
	# 1 -> 0 transition), so a row would always throw there first.

	if not dependants:
		return

	listed = ", ".join(dependants[:MAX_LISTED_DEPENDANTS])
	if len(dependants) > MAX_LISTED_DEPENDANTS:
		listed += " " + _("and {0} more").format(len(dependants) - MAX_LISTED_DEPENDANTS)

	frappe.throw(
		_("Cannot turn off Billable while these are still billable: {0}. Unbill them first.").format(listed)
	)
