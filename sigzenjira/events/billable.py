import frappe
from frappe import _
from frappe.utils import cint, get_link_to_form

from sigzenjira.events.task import WORK_ITEM_TYPE_PRIVILEGED_ROLES
from sigzenjira.permission.project_user import user_has_project_flag

# The Billable flag is one concept but three fieldnames - the custom field naming
# convention carries the doctype (custom_<doctype>_<name>), so the shared
# "custom_is_billable" this module used to key off no longer exists. Every clamp
# below walks doctypes generically, so it must resolve the fieldname per doctype
# rather than assume one name. KeyError on an unmapped doctype is deliberate: a
# new doctype wired into PARENT_SOURCES / DEPENDANT_SOURCES without a field here
# should fail loudly, not silently read None and skip the clamp.
BILLABLE_FIELDS = {
	"Task": "custom_task_is_billable",
	"Project": "custom_project_is_billable",
	"Issue": "custom_issue_is_billable",
}


def billable_field(doctype):
	return BILLABLE_FIELDS[doctype]


# --- Permission gate: only privileged roles may change Billable ---


def _has_declared_source(doc):
	return any(doc.get(fieldname) for _parent_doctype, fieldname in PARENT_SOURCES.get(doc.doctype, ()))


def validate_billable_edit_permission(doc, method=None):
	# Billable is a money decision. Compared against the previous saved value
	# rather than blanket-blocked, so an Employee can still save unrelated edits
	# (status, progress) on a billable item without tripping this.
	if doc.is_new() and _has_declared_source(doc):
		# On a new doc under a declared parent the flag is a clamp question, not a
		# permission one: validate_billable_under_billable_parent already guarantees
		# it can only be 1 if EVERY declared parent is 1, so it was inherited, never
		# invented. Gating it here blocked the one thing an Employee may create - a
		# Sub-task - under billable work, and pushed them toward unticking it, which
		# is silent under-billing. A new doc with NO declared source (a Project, a
		# standalone Story) has nothing to inherit from, so it stays gated below.
		return

	if WORK_ITEM_TYPE_PRIVILEGED_ROLES & set(frappe.get_roles(frappe.session.user)):
		return

	before = doc.get_doc_before_save()
	field = billable_field(doc.doctype)
	previous = 0 if doc.is_new() else cint((before or {}).get(field))
	if cint(doc.get(field)) != previous:
		frappe.throw(_("Only a Director, Product Owner, or Projects Manager can change Billable."))

	if doc.doctype != "Task" or doc.custom_task_work_item_type != "Story":
		return

	# "Allocate Hour + Billable Check/Uncheck" on Project User hands the split grid
	# over outright - the rows only, never the Story's own flag, which the role
	# check above has already settled by the time we get here. The rows stay
	# clamped either way: validate_task_split_billable keeps a row from being
	# billable under a non-billable Story, and validate_split_row_unbilling still
	# blocks unticking a row that has billable Sub-tasks under it.
	if user_has_project_flag(doc.project, "custom_project_user_allocate_hours"):
		return

	before_rows = {row.name: cint(row.is_billable) for row in (before.custom_task_task_split if before else [])}
	# A row that didn't exist before inherits the Story's own flag (task.js seeds
	# it in custom_task_split_add) - inherited, never invented, the same
	# carve-out made above for a new doc under a declared parent. Only for a user
	# who may work the split table at all, though: for anyone else a new row
	# still measures against 0, so a plain Employee cannot introduce billable
	# work. Without this, a grant holder could not split a billable Story at all,
	# and unticking to get past it is the silent under-billing this gate stops.
	# Set Work Item Type is the only flag left to check here - Allocate Hour
	# returned above.
	story_billable = (
		cint(doc.get(field))
		if user_has_project_flag(doc.project, "custom_project_user_set_work_item_type")
		else 0
	)
	for row in doc.get("custom_task_task_split") or []:
		if cint(row.is_billable) != before_rows.get(row.name, story_billable):
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
	if not cint(doc.get(billable_field(doc.doctype))):
		return

	for parent_doctype, fieldname in PARENT_SOURCES.get(doc.doctype, ()):
		parent = doc.get(fieldname)
		if not parent:
			continue
		if not cint(frappe.db.get_value(parent_doctype, parent, billable_field(parent_doctype))):
			frappe.throw(
				_("{0} {1} is not billable, so this {2} cannot be billable.").format(
					parent_doctype, get_link_to_form(parent_doctype, parent), doc.doctype
				)
			)


def validate_task_split_billable(doc, method=None):
	# The split rows live on the Story, so their "parent" for clamp purposes is
	# the Story itself - checked here rather than in PARENT_SOURCES because a
	# child row is not a doc with its own validate().
	if doc.custom_task_work_item_type != "Story" or cint(doc.get(billable_field(doc.doctype))):
		return

	for row in doc.get("custom_task_task_split") or []:
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
	if cint(doc.get(billable_field(doc.doctype))) or doc.is_new():
		return

	before = doc.get_doc_before_save()
	if not before or not cint(before.get(billable_field(doc.doctype))):
		return

	dependants = []
	for child_doctype, fieldname in DEPENDANT_SOURCES.get(doc.doctype, ()):
		dependants += frappe.get_all(
			child_doctype,
			filters={fieldname: doc.name, billable_field(child_doctype): 1},
			pluck="name",
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


def validate_split_row_unbilling(doc, method=None):
	# Unticking a row's Billable pushes 0 onto its generated Task through a raw
	# db.set_value in sync_split_row_edits_to_generated_task, which skips
	# validate() - so validate_no_billable_dependants never sees it and billable
	# Sub-tasks would be left hanging under a Task that just stopped being
	# billable. Editing that Task directly throws; this closes the grid's way
	# around it.
	if doc.custom_task_work_item_type != "Story" or doc.is_new():
		return

	before = doc.get_doc_before_save()
	if not before:
		return

	before_rows = {row.name: cint(row.is_billable) for row in before.get("custom_task_task_split") or []}

	for row in doc.get("custom_task_task_split") or []:
		if cint(row.is_billable) or not before_rows.get(row.name) or not row.generated_task:
			continue

		dependants = frappe.get_all(
			"Task",
			filters={"parent_task": row.generated_task, billable_field("Task"): 1},
			pluck="name",
		)
		if dependants:
			frappe.throw(
				_(
					"Cannot turn off Billable on row {0} while these are still billable: {1}. Unbill them first."
				).format(row.idx, ", ".join(dependants[:MAX_LISTED_DEPENDANTS]))
			)
