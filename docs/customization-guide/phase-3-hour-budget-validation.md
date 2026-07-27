# Phase 3 — Hour Budget Validation (hard block)

## Goal
A Story's children can't collectively promise more hours than the Story
itself was budgeted, and same for a Task under its Story:
- Sum of `expected_time` across all Stories sharing the same parent Epic
  (including the one being saved) must not exceed that Epic's
  `expected_time`.
- Sum of `expected_time` across all Tasks sharing the same parent Story
  (including the one being saved) must not exceed that Story's
  `expected_time`.
- Sub-task is excluded entirely — no budget check ever applies to it.
- Applies to every save, not just creation: editing an existing sibling's
  `expected_time` upward is checked the same way.

This reuses core ERPNext's native `expected_time` field (already on Task,
already used for estimating effort) — no new field needed for the budget
itself, only the check.

## Where the code lives
```
sigzenjira/custom/task.py   — validate_hour_budget(doc, method)
sigzenjira/hooks.py         — doc_events["Task"]["validate"] is now a LIST
```

Multiple functions can hook the same event for the same doctype — `hooks.py`
just needs `"validate"` to be a list instead of one string:

```python
doc_events = {
    "Task": {
        "before_validate": "sigzenjira.custom.task.mark_parent_as_group",
        "validate": [
            "sigzenjira.custom.task.validate_hierarchy",
            "sigzenjira.custom.task.validate_hour_budget",
        ],
    }
}
```

Order matters here: `validate_hierarchy` (Phase 2) runs first and would
already reject a Task whose parent isn't actually a Story, a Story whose
parent isn't actually an Epic, etc. `validate_hour_budget` runs second and
can safely assume — if it got this far — that `parent_task`, if set, really
is the correct type of container to sum against.

## The logic
```python
def validate_hour_budget(doc, method):
    if doc.custom_work_item_type not in BUDGET_CHECKED_TYPES or not doc.parent_task:
        return

    parent_budget = flt(frappe.db.get_value("Task", doc.parent_task, "expected_time"))

    sibling_hours = flt(frappe.db.sql(
        """select sum(expected_time) from `tabTask`
           where parent_task = %s and custom_work_item_type = %s and name != %s""",
        (doc.parent_task, doc.custom_work_item_type, doc.name or ""),
    )[0][0])

    total_hours = sibling_hours + flt(doc.expected_time)
    if total_hours > parent_budget:
        frappe.throw(...)
```

- `BUDGET_CHECKED_TYPES = {"Story", "Task"}` — Epic is the top of the tree
  (nothing above it to check against), Sub-task is excluded by spec. Both are
  skipped immediately.
- **Standalone Story/Task (no `parent_task`, allowed since Phase 2) has
  nothing to check against — skipped.** The budget check is inherently a
  property of the *parent-child relationship*, not the task in isolation; a
  task that opted out of that relationship opts out of its budget too.
- `name != %s` excludes the record's own previous DB value from the sibling
  sum so its *current* (possibly just-edited) `expected_time` isn't double
  counted — the query sums every *other* sibling, then `doc.expected_time`
  (the in-memory, about-to-be-saved value) is added on top. This is what
  makes the check work identically for both a brand new Task and an edit to
  an existing one's hours, with no separate "is this an update" branch.
- `flt(...)` guards against `None` (an Epic/Story with no `expected_time` set
  yet, or a `SUM()` over zero rows, both come back `NULL`/`None` from
  MariaDB) — `flt(None) == 0.0`.

## How it was verified
A throwaway test ran the exact worked example from the plan against
`mysite.in`: Epic (10h) → Story-1 (4h), Story-2 (6h) both save, total exactly
10h; Story-3 with any hours blocked. Story-2 (6h) → T1 (1h), T2 (3h), T3 (2h)
all save, total exactly 6h; T4 with any hours blocked. A Sub-task under T1
with 999h saved without issue (excluded from the check). Editing T1's hours
upward so the Story-2 total would exceed 6h was blocked on save, not just on
creation. A standalone Story with 9999h saved fine (no parent to check
against). All 11 cases passed; every test record was deleted afterward.
