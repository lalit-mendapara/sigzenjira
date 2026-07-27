# Phase 4 — Additional Hours Request doctype + workflow

## Goal
A new doctype an Employee fills out to ask for more hours on a Task that's
running over budget. A Projects Manager approves or rejects it. Rollup of
the approved hours into `extra_hours` is Phase 5 — this phase is just the
request record and its approval workflow.

## Fields
- `task` (Link → Task) — picker filtered to `custom_work_item_type = Task` only
- `requested_by` (Link → User) — defaults to the creating user (`default: "__user"`)
- `additional_hours_requested` (Float)
- `reason` (Small Text, **mandatory**)
- `status` (Select: Draft/Pending/Approved/Rejected, `read_only: 1` — driven
  entirely by the workflow, never hand-edited)
- `approved_by` (Link → User, `read_only: 1`, auto-set when a Projects Manager
  approves)

## Where this doctype's own customization goes — different pattern than Task
Task/Timesheet are doctypes owned by `erpnext` — extending them means
`doc_events` hooks in `hooks.py` pointing at functions living in
`sigzenjira/custom/`, since we can't add methods to a controller class we
don't own.

**Additional Hours Request is a doctype `sigzenjira` owns.** Its own
`validate()` goes directly in its own controller class — the idiomatic,
simpler pattern for a doctype the app defines itself:

```
sigzenjira/sigzenjira/doctype/additional_hours_request/
    additional_hours_request.json   — schema (auto-exported, developer_mode)
    additional_hours_request.py     — AdditionalHoursRequest(Document): def validate(self): ...
    additional_hours_request.js     — frm.set_query("task", ...) — its own field, no override needed
```

Created via `frappe.get_doc({"doctype": "DocType", ...}).insert()` in a
one-off script — with `developer_mode: 1` (already set in this bench's
`site_config.json`), inserting a new DocType automatically writes its
json/py/js files to disk, same result as building it through the Desk UI.

## Server-side re-check (link filters are UI-only)
The `task` field's client-side query (`custom_work_item_type: "Task"`) only
restricts what the Desk picker *offers* — it does nothing to stop an API call
that sets `task` directly to an Epic/Story/Sub-task. `validate()` re-checks
the same rule server-side:

```python
def validate(self):
    work_item_type = frappe.db.get_value("Task", self.task, "custom_work_item_type")
    if work_item_type != "Task":
        frappe.throw(...)
    if self.status == "Approved" and not self.approved_by:
        self.approved_by = frappe.session.user
```

## Permissions — Employee sees only their own requests
`DocPerm` rows alone can't express "only rows I created" — per this repo's
own carried-over gotcha, `if_owner` on a DocPerm row kills list/report
access entirely rather than scoping it. The correct mechanism is
`permission_query_conditions` (filters what shows in lists/reports) +
`has_permission` (gates a specific document):

```python
def get_permission_query_conditions(user=None):
    if "Projects Manager"/"System Manager" in roles: return ""
    return f"...requested_by = {frappe.db.escape(user)}"

def has_permission(doc, user=None, permission_type=None):
    if "Projects Manager"/"System Manager" in roles: return True
    if permission_type == "create": return True   # see gotcha below
    return doc.requested_by == user
```

Wired via `hooks.py`'s `permission_query_conditions` / `has_permission` dicts
(same mechanism the hooks.py template shows for core's own Event doctype).

### A real gotcha hit while testing: `has_permission` on create
The first version didn't special-case `permission_type == "create"`, and
every Employee-created request failed with `PermissionError` despite the
role having `create: 1`. Cause: a brand-new, unsaved document has no
`requested_by` yet, so `doc.requested_by == user` evaluated to `None == user`
→ `False` → **denied**, overriding the role-level create permission
entirely. This is the same "hook must explicitly return, never fall through
to a falsy default" gotcha already on file for `has_permission` — row-level
ownership scoping only makes sense once a document (and its owner) actually
exists, so `create` needs to defer to the role permission unconditionally.

## The Workflow
```python
Workflow(
    document_type="Additional Hours Request",
    workflow_state_field="status",   # our own field, not a hidden extra one
    states=[Draft(Employee), Pending(PM), Approved(PM), Rejected(PM)],
    transitions=[
        Draft --Submit--> Pending     (allowed: Employee),
        Pending --Approve--> Approved (allowed: Projects Manager),
        Pending --Reject--> Rejected  (allowed: Projects Manager),
    ],
)
```

### A real gotcha: Workflow States/Actions are Link fields, not free text
A `Workflow`'s `states` and `transitions` child tables don't take plain
strings — `state` links to a `Workflow State` master doctype and `action`
links to `Workflow Action Master`. Core Frappe ships `Pending`/`Approved`/
`Rejected` and `Approve`/`Reject` as defaults already, but **not** `Draft` or
`Submit`, which this workflow needed — those two master records had to be
created first, or `Workflow.insert()` fails with `LinkValidationError`.

## Task's own permissions needed a fix too
Core `Task` ships permission rows for `Projects User`, `HR User`,
`HR Manager` only — no `Projects Manager` row at all (this repo's own
carried-over gotcha). Without one, a Projects Manager approving/rejecting a
request couldn't even open the linked Task to see what they were approving.
Added via `Custom DocPerm` (the correct way to grant a role extra permissions
on a doctype the app doesn't own — never edit `apps/erpnext` directly).

## Where the code lives
```
sigzenjira/sigzenjira/doctype/additional_hours_request/   — doctype + controller + client script
sigzenjira/install.py             — create_task_projects_manager_docperm(), create_additional_hours_request_workflow()
sigzenjira/patches/v0_0/add_additional_hours_request_workflow.py   — same, for the already-installed site
sigzenjira/hooks.py               — permission_query_conditions, has_permission
```

## How it was verified
A throwaway test built a full Task hierarchy, then: confirmed raising a
request against an Epic/Story/Sub-task is rejected server-side (bypassing
the UI filter entirely via the Document API); confirmed a missing `reason`
blocks the save; created two real test users — critically, the "Employee"
one needed an actual `Employee` master record linked via `user_id`, because
core ERPNext strips the `Employee` role from any User with no linked
Employee record on every save (`erpnext/setup/doctype/employee/employee.py`)
— then, as that Employee, created a request (confirmed `requested_by`
auto-filled, status `Draft`), submitted it to `Pending`, attempted to
self-approve (blocked — the `Approve` transition isn't even offered to a
non-Projects-Manager role), then switched to the Projects Manager user and
approved it (confirmed status → `Approved`, `approved_by` auto-set to the
approving manager). All 10 cases passed; every test record was deleted
afterward.
