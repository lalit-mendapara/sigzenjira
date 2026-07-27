# Phase 4b — Warn before submitting a Timesheet over budget

Not in the original plan, requested after Phase 4. Goal: before a Timesheet
gets submitted, if it would push a Task's Actual Time past its budgeted
Expected Time, show a warning with a button that jumps straight to a new
Additional Hours Request pre-filled for that task — rather than blocking the
submit outright, since the user might just be catching up on logging time
they already worked.

## The hook: `before_submit`, and why it has to return a promise
Frappe's `savesubmit()` flow (`frappe/public/js/frappe/form/form.js`):
1. Shows its own native "Permanently Submit?" confirm.
2. Sets `frappe.validated = true`.
3. Triggers `before_submit` and **awaits it** (`script_manager.trigger`
   checks whether the handler returned something thenable, and if so waits
   for it before continuing) — this only works if the handler actually
   `return`s the promise, not just fires it.
4. After that resolves, checks `frappe.validated` — if it's `false`, the
   submit stops there.

So the handler:
```js
before_submit: function (frm) {
  frappe.validated = false;                 // hold the submit
  return frappe.call({ ... }).then((r) => {  // MUST be `return`ed
    if (no warnings) { frappe.validated = true; return; }
    // ...show dialog, leave frappe.validated false...
  });
}
```
If `.then()` doesn't get `return`ed, the trigger resolves immediately
(synchronously, before the server call responds), `frappe.validated` is
still `false` from the top of the function, and the submit is blocked
*every* time regardless of the actual check result — the async check has to
be awaited or the whole thing just always blocks.

## The dialog: two ways forward, not a hard block
The requirement was to *notify*, not prevent — a `frappe.ui.Dialog` with
`primary_action` ("Request Additional Hours" → `frappe.new_doc("Additional
Hours Request", {task: ...})`, navigating away without submitting) and
`secondary_action` ("Submit Anyway" → sets a one-shot `frm.__skip_budget_check`
flag and calls `frm.savesubmit()` again, letting the retry through without
re-asking). Both `secondary_action`/`secondary_action_label` are real
`Dialog` options (`frappe/public/js/frappe/ui/dialog.js`).

## The check itself — projecting, not just reading
`Task.actual_time` only reflects *already-submitted* Timesheets
(`recompute_actual_time` filters `docstatus = 1`) — the one currently being
submitted isn't counted yet. So the server-side check adds this timesheet's
own hours on top of the task's current `actual_time` to see what submitting
*would* result in, rather than comparing against a stale pre-submission
number:

```python
@frappe.whitelist()
def check_over_budget(timesheet_name):
    for each task referenced in this (still-Draft) timesheet's time_logs:
        projected = task.actual_time (current) + this_timesheet's_hours_for_that_task
        if projected > task.expected_time:
            warn
```

## Sub-task hours check the parent Task's budget
Sub-task has no `expected_time` of its own (by Phase 1 design — "hide or
leave unused on Sub-task, no validation will reference it there"). So
`_budget_task()` resolves which Task's budget actually matters: itself, if
logging directly against a Task; its parent Task, if logging against a
Sub-task.

## Where the code lives
```
sigzenjira/custom/timesheet.py      — _budget_task, check_over_budget (whitelisted)
sigzenjira/public/js/timesheet.js   — before_submit hook + Dialog
```

## How it was verified
The whitelisted `check_over_budget` function (the only part testable without
a browser) was tested directly: logging 3h against a 5h-budget Task produced
no warning; submitting that 3h for real, then drafting a second 4h entry
against the same task (3 actual + 4 pending = 7h > 5h) produced a warning
with the correct projected total and budget; logging 10h against a Sub-task
whose parent Task already had 3h actual (3 + 10 = 13h > 5h) correctly warned
against the *parent Task*, not the Sub-task. All 6 cases passed. The dialog
and its buttons are pure client-side UI and need a real browser check.
