# Phase 5 — Approval → extra_hours rollup

## Goal
When a Projects Manager approves an Additional Hours Request: the linked
Task's `extra_hours` gains the approved amount, its parent Story's
`extra_hours` becomes the sum across all its child Tasks, and its
grandparent Epic's `extra_hours` becomes the sum across all its child
Stories. Rejecting a request must never touch `extra_hours` anywhere.

## Where the code lives — same doctype, `on_update` this time
Continuing Phase 4's pattern (this is our own doctype, so the logic lives in
its own controller, not a `doc_events` hook):

```
sigzenjira/sigzenjira/doctype/additional_hours_request/additional_hours_request.py
    on_update()               — detects the transition INTO Approved
    rollup_extra_hours()      — sets the Task's own extra_hours
    _rollup_ancestor_extra_hours()  — walks Story/Epic up as pure sums
```

`validate()` (Phase 4) stays about the document's own fields —
`approved_by` gets set there. The `extra_hours` rollup is a side effect on a
*different* document (the Task), which is why it lives in `on_update`
instead: `validate` runs before the document's own save is finalized,
`on_update` runs after, which is the more idiomatic place to trigger effects
elsewhere once this document's own state is settled.

## Only fire once, only on Approve, never on Reject
A workflow transition just sets `status` and calls `doc.save()` like any
other edit — so `on_update` fires on *every* save of an Additional Hours
Request, including ones that have nothing to do with a fresh approval (e.g.
someone re-saving an already-Approved request after fixing a typo in
`reason`). Re-adding the hours on every such save would keep inflating
`extra_hours` forever. Guarded with `get_doc_before_save()` (the document's
state as it was loaded, before this save's changes):

```python
def on_update(self):
    before = self.get_doc_before_save()
    just_approved = self.status == "Approved" and (not before or before.status != "Approved")
    if just_approved:
        rollup_extra_hours(self.task, flt(self.additional_hours_requested))
```

Rejected transitions do nothing here at all — not "roll up zero", just never
call the rollup functions — which is what makes "rejecting never touches
extra_hours anywhere" true by construction rather than by an extra check.

## Why Story/Epic use a different formula than Task
```python
def rollup_extra_hours(task_name, additional_hours):
    task.custom_extra_hours = task.custom_extra_hours + additional_hours   # Task: ADD
    _rollup_ancestor_extra_hours(task.parent_task)

def _rollup_ancestor_extra_hours(task_name):
    children_total = sum(custom_extra_hours across all tasks with parent_task = task_name)
    # Story/Epic: pure SUM of children, no "own" additional_hours to add
    ...recurse upward...
```
An Additional Hours Request only ever targets a Task (Phase 4's own
validation guarantees this), so a Story or Epic never has a *direct* approved
amount of its own the way a Task does — its `extra_hours` is always entirely
derived from its children. This is different from Phase 3b's `actual_time`
rollup, which does allow a direct component at every level (since Timesheet
entries can be logged straight against a Task, not just a Sub-task).

## Fixed a gap this surfaced: Phase 4b's budget warning ignored extra_hours
Once hours are approved, the *effective* budget for the over-budget Timesheet
warning (Phase 4b) is `expected_time + extra_hours`, not just
`expected_time` — otherwise the warning would keep firing on every timesheet
even after additional hours were granted for exactly that overrun.
`check_over_budget` (`sigzenjira/custom/timesheet.py`) now fetches
`custom_extra_hours` alongside `expected_time` and compares against their
sum.

## How it was verified
A throwaway test built Epic → Story → (T1, T2), then: raised +2h against T1
and approved it (confirmed T1=2h, Story=2h, Epic=2h); raised +1h against T2
and approved it (confirmed Story updates to 3h = 2+1, Epic updates to 3h);
raised +5h against T1 again but **rejected** it (confirmed T1/Story/Epic all
stayed exactly where they were — untouched). Then, for the Phase 4b fix:
logged 6h against T1 (5h expected + 2h approved extra = 7h effective budget)
— no warning, correctly under the *effective* budget even though 6h alone
already exceeds the 5h `expected_time`; logged 2h more (6 actual + 2 new =
8h > 7h effective) — correctly warned. All 10 cases passed; every test
record was deleted afterward.
