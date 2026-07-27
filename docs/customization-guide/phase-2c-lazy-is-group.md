# Phase 2c — is_group reflects reality, not just possibility

Not in the original plan — a refinement of the Phase 2 `is_group` handling.

## First version was "eager", changed to "lazy"
The first version forced `is_group = 1` on every Epic/Story/Task the moment
*it* was saved, regardless of whether it actually had any children yet — it
was set purely because that type is *allowed* to have children. So a brand
new empty Story would immediately show as a group/folder.

Changed to match what `is_group` should actually mean: a task is a group
because it *has* children, not because its type theoretically permits them.
Now `is_group` starts unchecked on every new task, and only flips on the
moment a real child gets created under it.

## The tricky part: hook execution order
Frappe's `doc_events` hooks for the same event (e.g. `validate`) always run
**after** the doctype's own core controller method for that event
(`document.py`'s `Document.hook()` composes `[core_method, *doc_event_hooks]`
in that order, not the reverse).

Core `Task.validate()` (`erpnext/projects/doctype/task/task.py`,
`validate_parent_is_group`) checks the *parent's* `is_group` value in the DB
and throws *"must be a Group Task"* if it's unchecked. If we tried to flip the
parent's `is_group` from a `validate` hook on the child, core's own check on
that same child would already have run and thrown — one step too late.

Fix: hook `before_validate` instead of `validate` for this specific piece.
`before_validate` runs as a fully separate, earlier step
(`document.py`'s `_validate()` calls `run_method("before_validate")` before
`run_method("validate")`), so the parent's `is_group` is already `1` in the
DB by the time core's check on the child runs.

```python
def mark_parent_as_group(doc, method):
    if doc.parent_task and not frappe.db.get_value("Task", doc.parent_task, "is_group"):
        frappe.db.set_value("Task", doc.parent_task, "is_group", 1)
```

```python
doc_events = {
    "Task": {
        "before_validate": "sigzenjira.custom.task.mark_parent_as_group",
        "validate": "sigzenjira.custom.task.validate_hierarchy",
    }
}
```

`validate_hierarchy` (the Phase 2 hierarchy check) still runs afterward as
normal and can still block the save for an invalid parent type — if it does,
the whole transaction (including the `is_group` flip) rolls back, so nothing
inconsistent gets persisted.

## What was deliberately left out
- **Un-flipping `is_group` back to 0** when the last child under a task is
  deleted or re-parented elsewhere isn't handled — only asked for the
  "turns on when a child appears" direction. Add a `before_validate`/`on_trash`
  check (count remaining children) if that reverse case starts mattering.
- Manually unchecking "Is Group" on a task that still has children via the
  Desk UI isn't guarded against — not asked, and an unusual thing for someone
  to do on purpose.

## How it was verified
A throwaway test created a Story with no children (`is_group` stayed 0), then
a Task under it (`is_group` flipped to 1), then a Sub-task under that Task
(its `is_group` flipped to 1 too), then a second Task under the same Story
(no error — idempotent, already 1). The full Phase 2 hierarchy regression
suite (12 valid/invalid cases) was re-run afterward to confirm removing the
old eager assignment didn't break anything.
