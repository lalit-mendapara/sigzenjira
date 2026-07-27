# Phase 2 — Hierarchy Validation (hard block)

## Goal
Enforce that a Task's `parent_task` matches its `custom_work_item_type`:
- Epic → no parent allowed
- Story → parent is optional (a Story doesn't have to belong to an Epic), but
  if given, it must be an Epic
- Task → parent is optional (small standalone tasks don't need a Story), but
  if given, it must be a Story
- Sub-task → parent must be a Task (mandatory, no exception)

Any mismatch blocks the save with a clear error.

**Design call, not in the original written spec**: the plan initially had every
level's parent as mandatory. In practice both Stories and Tasks can exist
without a level above them, so both were relaxed to optional-if-absent,
still-validated-if-present. Epic (top of the tree) and Sub-task (always
belongs to a specific Task) keep their hard requirement — there's no
"standalone Sub-task" concept.

## The ERPNext-correct way to add logic to a core doctype
Same rule as Phase 1: never touch `apps/erpnext`. For *behavior* (as opposed to
schema/fields), the standard extension point is the **`doc_events`** hook in
`hooks.py`. It lets a custom app attach a function to any lifecycle event
(`validate`, `on_update`, `before_insert`, `on_submit`, ...) of *any* doctype,
including ones the app doesn't own:

```python
doc_events = {
    "Task": {
        "validate": "sigzenjira.custom.task.validate_hierarchy",
    }
}
```

Frappe calls `validate_hierarchy(doc, method)` every time a Task is saved,
*in addition to* Task's own built-in `validate()` — it doesn't replace core
behavior, it layers on top of it. This is why the app never needs to subclass
or monkey-patch the `Task` controller.

(There's also `extend_doctype_class` for when you need to override or wrap an
existing controller *method* rather than just hook a lifecycle event — not
needed here, `doc_events` is the simpler and more common tool for this kind
of rule.)

## Where the code lives
```
sigzenjira/custom/task.py   — validate_hierarchy(doc, method)
sigzenjira/hooks.py         — doc_events wiring
```

## The logic
A lookup table maps each `custom_work_item_type` value to the value its
parent is required to have (`None` for Epic, meaning "no parent"). The table
keys are the Select field's *option values* (`"Epic"`, `"Story"`, ...), not
fieldnames, so they're unaffected by whatever the underlying field is called:

```python
EXPECTED_PARENT_TYPE = {
    "Epic": None,
    "Story": "Epic",
    "Task": "Story",
    "Sub-task": "Task",
}
```

`validate_hierarchy` looks up the doc's own expected parent type, then:
- Epic case (`expected_parent_type is None`) → throw if `parent_task` is set at all.
- Empty `parent_task` → throw, *unless* `custom_work_item_type` is in
  `OPTIONAL_PARENT_TYPES` (`{"Story", "Task"}`), in which case it's allowed to
  stand alone.
- Non-empty `parent_task` → always checked regardless of type: throw if
  `frappe.db.get_value("Task", doc.parent_task, "custom_work_item_type")` doesn't
  match what's expected. A standalone Story or Task can still choose to attach
  to an Epic/Story later — it just can't attach to the wrong thing.

## A real ERPNext gotcha we hit
`Task` is a **NestedSet** tree doctype (`is_tree: 1`, `nsm_parent_field:
"parent_task"`). Core Frappe refuses to let you set `parent_task` to a task
that isn't flagged `is_group = 1` — it throws *"must be a Group Task"* — even
though `is_group` has nothing to do with our own Epic/Story/Task/Sub-task
classification.

How `is_group` gets managed automatically is covered separately in
[Phase 2c](phase-2c-lazy-is-group.md) — it starts unchecked and flips on the
moment a real child is created under it, rather than being forced on just
because a task's type could theoretically have children.

## How it was verified
A throwaway test module ran all 8 combinations from the Phase 2 test plan
plus a few extra (invalid-parent-type cases for every level, plus standalone
Story and standalone Task) directly against `mysite.in` via
`frappe.get_doc(...).insert()`, then deleted every test record. All passed:
- Each invalid parent/child combination rejected with a clear error
- Each valid combination (Epic→Story→Task→Sub-task) saves
- Standalone Story (no Epic) and standalone Task (no Story) both save
- Sub-task always requires a Task parent — no standalone case, unchanged
- Sub-task under a Task saves with no `expected_time` required (Phase 3's
  budget check doesn't touch Sub-task at all, so nothing to verify here yet)
