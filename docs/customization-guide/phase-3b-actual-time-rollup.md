# Phase 3b — Roll up Actual Time (via Timesheet) up the hierarchy

Not in the original plan, requested before Phase 4. Goal: when someone logs
hours on a Sub-task (or directly on a Task, if it has no Sub-tasks), that
time should be visible in `Actual Time in Hours (via Timesheet)` all the way
up: Sub-task → Task → Story → Epic.

## Why this needed care — CLAUDE.md's `actual_time` gotcha
This repo's own notes flag `Task.actual_time` as risky to touch: "it feeds
Project costing." Checked the actual core code before writing anything:

- `Task.actual_time` (`erpnext/projects/doctype/task/task.py`,
  `update_time_and_costing`) = `SUM(Timesheet Detail.hours WHERE task = this
  task)`. Direct entries only — no concept of children today.
- `Project.actual_time` (`erpnext/projects/doctype/project/project.py`,
  `update_costing`) = `SUM(Timesheet Detail.hours WHERE project = this
  project)`, queried independently, **not** derived from `Task.actual_time`.
  So a Task/Story/Epic-level rollup can't double-count into Project costing —
  they're separate queries against the same raw Timesheet Detail rows.

The real risk was a different one: `Task.update_time_and_costing()` runs
automatically every time a Timesheet referencing that exact task is
submitted/cancelled, and it *overwrites* `actual_time` from a direct-only
query. If our rollup value was sitting on a Story/Epic that later received a
direct Timesheet entry, core would silently stomp it. Decided (with the
user) that Epic/Story never get direct entries — only Task and Sub-task do,
since Sub-task is optional and a worker might just log time straight on the
Task if they didn't bother breaking it down further.

## The design
Rather than trying to layer a rollup *on top of* whatever core last wrote
(fragile — depends on hook ordering, and a plain unrelated Task save would
double-count children on top of an already-merged value), `recompute_actual_time`
always computes the **canonical value from raw sources**, ignoring whatever
was there before:

```python
def recompute_actual_time(task_name):
    direct_hours = <sum of Timesheet Detail.hours for this task, docstatus=1>
    children_hours = <sum of actual_time across tasks whose parent_task = this task>
    frappe.db.set_value("Task", task_name, "actual_time", direct_hours + children_hours, ...)
    parent_task = <this task's parent_task>
    if parent_task:
        recompute_actual_time(parent_task)  # walk up the chain
```

Called for every unique task referenced in a Timesheet's `time_logs`, from
`on_submit` and `on_cancel` (not `validate`/`on_update` — nothing about
`actual_time` should ever be touched by an unrelated Task save, only by an
actual Timesheet event). Recursion walks the whole chain up to Epic in one
call, so a Sub-task's 3 hours become visible at every level above it
immediately.

Because it always recomputes from the raw Timesheet Detail + children query
instead of adding to the existing value, it's naturally correct whether a
task has direct entries, child entries, both, or (after a cancel) fewer of
either — no separate "is this an update" or "is this a cancel" branch needed.

## Enforcing Epic/Story never get direct entries
Two layers, same pattern as every other filter in this app (UI convenience +
server enforcement, since link filters are UI-only):

- **Client**: `sigzenjira/public/js/timesheet.js` filters the `task` field
  inside Timesheet's `time_logs` child table to
  `custom_work_item_type in (Task, Sub-task)`.
- **Server**: `validate_task_type` (hooked on Timesheet's `validate`) rejects
  any row whose task isn't Task/Sub-task, with a clickable link to the
  offending task.

## Where the code lives
```
sigzenjira/custom/timesheet.py         — validate_task_type, recompute_actual_time, rollup_actual_time
sigzenjira/public/js/timesheet.js      — client-side task-field filter
sigzenjira/hooks.py                    — doc_events["Timesheet"] + doctype_js["Timesheet"]
```

## Existing real data needed a one-time backfill
Two of the project's own real Timesheets predate this feature, so their
Sub-tasks already had `actual_time` set but it had never propagated upward.
Ran `recompute_actual_time` once for every existing Task to backfill —
`TASK-2026-00005` (2h) now correctly shows up the whole chain: Sub-task 2h →
Task 2h → Story 2h → Epic 5h (2h from this branch + 3h from the other Story's
branch).

## How it was verified
A throwaway test built a full Epic→Story→Task→Sub1/Sub2 tree, then: logged
3h on Sub1 (verified it appears at every level up to Epic), logged 4h on Sub2
(verified Task/Story/Epic now show 7h, both subtasks summed correctly),
logged 2h directly on the Task itself with no Sub-task involved (verified
Task/Story/Epic show 9h — direct entry added on top of the children sum, not
replacing it), then cancelled the first Timesheet (verified Sub1 drops to 0
and Task/Story/Epic drop to 6h). Also confirmed a Timesheet entry logged
directly against a Story is rejected server-side. All 15 cases passed; every
test record was deleted afterward.
