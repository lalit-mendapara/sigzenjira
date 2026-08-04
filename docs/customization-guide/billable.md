# Billable — Project → Issue → Story → Task Split → Task → Timesheet

## Goal
One boolean — "is this work billable to the customer?" — that starts at the
Project, flows down the existing work-item chain as a *default*, and ends by
driving the billing core ERPNext already computes on Timesheet rows. Nothing
new is created to carry it: the chain that already exists

```
Project ──► Epic ─────────────────► Story ──► Task Split row ──► generated Task ──► Timesheet Detail
   │                                  ▲                                   │
   └────► Issue ──(make_story)────────┘                                   ▼
                                                                       Sub-task ──► Timesheet Detail
```

is what Billable rides. The Issue branch is an optional entry point, not the
spine — a greenfield Project with an Epic and Stories and no Issue anywhere
is fully covered: an Epic clamps straight against its Project.

Core ERPNext already has `Timesheet Detail.is_billable` (Check, default 0),
already driving `billing_hours`, `billing_rate`, `base_billing_amount`, the
Timesheet's `total_billable_hours`, and Sales-Invoice-from-Timesheet — and
`custom/timesheet.py:recompute_actual_time` (called from `rollup_actual_time`
on Timesheet submit/cancel) already rolls `base_billing_amount` up into
`Task.total_billing_amount`. So this feature adds **no billing arithmetic at
all**. It only has to make sure the right value lands in that existing
field.

## 1. Where the flag lives
One Check field, `custom_is_billable`, default `0`, added to three doctypes
(`custom/custom_fields.py`, synced via `sigzenjira/install.py:sync_custom_fields`):

| Doctype | Field | Placement |
|---|---|---|
| Project | `custom_is_billable` | after `is_active` |
| Issue | `custom_is_billable` | after `project` |
| Task | `custom_is_billable` | after `custom_work_item_type` |
| Task Split | `is_billable` (no prefix — this is the app's own doctype, not a customization) | after `expected_hours`, `in_list_view: 1` |

A single Check on Task covers all four work item types — a Sub-task needs the
flag as much as a Task does, because `custom/timesheet.py:validate_task_type`
permits logging time against either. `Timesheet Detail` gets no new field:
core's own `is_billable` is reused (see §5).

The `Custom Field` fixture filter (`hooks.py`) widens to
`dt in ["Task", "Project User", "Project", "Issue"]` and the `Property
Setter` filter to `doc_type in ["Task", "Issue", "Timesheet Detail"]` so both
round-trip through git.

## 2. Propagation — the Desk sets defaults, the server only clamps
The server never guesses an initial value; it only validates one already set
(§3). Ticking the box for a fresh document is the Desk's job:

- `public/js/issue.js` — on `project` change, seeds `custom_is_billable` from
  that Project's flag.
- `public/js/task.js` — on `project` or `parent_task` change (`parent_task`
  wins when both are set), seeds from that source. Covers Epic-from-Project,
  Story-from-Epic, Task-from-Story, Sub-task-from-Task.
- Both scripts also run the same seeding once on `onload_post_render`, guarded
  by `frm.is_new()`. A field set by `frappe.route_options`,
  `frappe.defaults`, or a "Create Task"/"Create Sub-task" button fires no
  `change` event, so the change handlers alone would leave a greenfield Task
  at `0` on exactly the paths that matter most (Project → Create Task, the
  Work Board's create flow, Task → Create Sub-task). Both entry points share
  one `seed_billable_from_source(frm)` helper so they cannot drift apart.
- `public/js/task.js`'s `Task Split` handler block has its own
  `custom_task_split_add`: a newly added split row's `is_billable` starts at
  the Story's own flag.

**Seeding only ever runs on a new document — this is deliberate, not an
oversight.** Reparenting a saved Task, or changing its Project, never
rewrites an already-set `custom_is_billable`. A non-billable Task sitting
under a billable Story is a legitimate, intended state (the whole point of
the mixed-Story case in §3), so silently re-seeding it on every parent change
would quietly start billing work someone had deliberately marked free. The
`parent_task`/`project` handlers both guard on `frm.is_new()` for exactly this
reason.

Two server-side seeds exist because these creates never touch a form:

- `custom/issue.py:make_story()` copies `issue.custom_is_billable` onto the
  new (always standalone) Story.
- `custom/task.py:generate_tasks_from_split()` and
  `create_task_without_hours()` pass `custom_is_billable: row.is_billable`
  into the Task insert dict.

A document created through the REST API with no explicit value simply gets
`0`. There is no reliable way to distinguish "deliberately left unchecked"
from "never saw the field" for a Check, so the server does not try — the
clamp (§3) guarantees a `0` is never *wrong* in the dangerous direction; it
can only under-bill, never over-bill.

## 3. The clamp — `custom/billable.py`, both directions
A new module rather than more lines in the already-~600-line `task.py`,
because the rule spans Project, Issue and Task equally.

### Upward — "billable only under billable"
A doc's billable claim must hold against **every** source it declares, not
just the nearest one:

```python
PARENT_SOURCES = {
    "Task": (("Task", "parent_task"), ("Issue", "issue"), ("Project", "project")),
    "Issue": (("Project", "project"),),
    "Project": (),
}
```

`validate_billable_under_billable_parent` walks every entry that's actually
set and throws naming the first non-billable one. A Task Split row is
checked separately (`validate_task_split_billable`, since a child row has no
`validate()` of its own) against the Story it belongs to.

**Why every declared source, not the nearest one:** `make_story()` creates a
**standalone** Story — no `parent_task` — so a nearest-source rule would
resolve straight to the still-billable `project` and let someone flip a
deliberately-unbilled support Story back to billable with nothing throwing,
silently overriding the Issue's decision. This is the motivating case:
Project stays billable (past work was billed), a post-delivery support Issue
on it is unchecked, `make_story()` copies that `0` onto the new Story — and
because the clamp checks the Story's `issue` as well as its `project`, that
Story can never later be flipped back to billable while its Issue still says
otherwise. It costs nothing in the ordinary case: an Issue is itself clamped
against its Project, and a Task's parent chain is clamped all the way up, so
for any doc built through these rules the extra checks are already satisfied
by transitivity — they only bite where two branches genuinely disagree, which
is exactly when they should.

### Downward — "no billable dependants left behind"
```python
DEPENDANT_SOURCES = {
    "Project": (("Task", "project"), ("Issue", "project")),
    "Issue": (("Task", "issue"),),
    "Task": (("Task", "parent_task"),),
}
```
`validate_no_billable_dependants` only fires on a real `1 → 0` transition
(new docs and already-unbilled saves cost one flag check and return). It
throws, naming up to `MAX_LISTED_DEPENDANTS` (10) offenders, if anything
downstream is still billable. Unchecking a Project with a billable Issue on
it, or a Story with a billable Task, is blocked the same way — the mirror
image of the upward rule, read from the other side. The alternative (silently
cascading the un-bill down through every descendant) was rejected: this is a
money decision, and a silent bulk rewrite of billing state is exactly the
failure mode the whole feature exists to prevent.

A Story and its own Task Split rows can be unbilled together in one save
**as long as none of those rows has generated a Task yet** — the DB still
holds `is_billable=1` on the child rows while the parent's `validate()` runs,
so reading rows from the DB here would wrongly block a save that legitimately
unbills both at once. `validate_task_split_billable` (the upward check)
already covers the split-row case more broadly than a downward check could (it
fires on any save where the Story's flag is off and a row's is on, not only on
a `1 → 0` transition), so there is no separate downward leg for split rows.

**Caveat once a row has generated a Task.** That Task is a real child `Task`
row in the DB with `custom_is_billable = 1`, and the row → Task push happens
in `on_update` — *after* `validate`. So on the one-save attempt,
`validate_no_billable_dependants` still sees the generated Task as billable
and throws naming it. The working sequence is two steps: unbill the generated
Task first (which pulls back onto its row via
`sync_expected_hours_to_split_row`), then unbill the Story.

### Downward, through the split grid — `validate_split_row_unbilling`
Unticking a **row's** Billable is legal on its own (a non-billable row under a
billable Story is a normal state), and `sync_split_row_edits_to_generated_task`
pushes that `0` onto the row's generated Task with a raw `frappe.db.set_value`
— which skips `validate()` entirely. Without a guard, that leaves any billable
Sub-task hanging under a Task that just stopped being billable, and it keeps
billing; the identical edit made by opening that Task directly throws. Since
the split grid is the *primary* editing surface for a Story, this was the
whole clamp's one-way hole.

`validate_split_row_unbilling` closes it: on a Story save, for every row going
`1 → 0` that has a `generated_task`, it looks for child Tasks of that
generated Task still marked billable and throws naming them. Unbill those
first, then the row.

## 4. Who may change it — `validate_billable_edit_permission`
Gated to `WORK_ITEM_TYPE_PRIVILEGED_ROLES` (Director / Product Owner /
Projects Manager / System Manager) — the same set `custom/task.py` already
uses for work-item-type and expected-time edits. One implementation in
`custom/billable.py`, used by all three doctypes plus the Task Split row
loop (guarded to only run when `doc.doctype == "Task"` and the type is
`Story`, so Project/Issue are unaffected by that extra leg).

On an **existing** doc the new value is compared against
`get_doc_before_save()` rather than blanket-blocked, so a non-privileged user
can still save unrelated edits (status, progress) on an already-billable item
without tripping this — only an actual change to the flag throws.

**On a new doc that declares a parent source, the gate is skipped entirely**
(`_has_declared_source(doc)` — any `PARENT_SOURCES` fieldname on the doc is
set). On a new doc the flag is a *clamp* question, not a permission one:
`validate_billable_under_billable_parent` already guarantees it can only be
`1` if **every** declared parent is `1`, so the value was inherited, never
invented.

This is not a convenience — gating it was actively harmful. `task.js`'s
`seed_billable_from_source` seeds `custom_is_billable = 1` from the parent on
`onload_post_render`, so an Employee clicking **Create Sub-task** on a billable
Task got `Only a Director, Product Owner, or Projects Manager can change
Billable.` on save. `validate_work_item_type_permission` makes Sub-task the
only type an Employee may create, so that was their *entire* creation path,
and their only way out was to untick the box — producing non-billable work
under a billable parent, i.e. the silent under-billing this feature exists to
prevent. The same applied to an Issue created on a billable Project.

A new doc with **no** declared source has nothing to inherit from, so it stays
gated: a new `Project` (`PARENT_SOURCES["Project"] = ()`), or a standalone
Story with neither `project` nor `issue` nor `parent_task`. There a `1` really
would be invented.

This rule also covers the three server-side creates that used to need
`doc.flags` escape hatches — `generate_tasks_from_split` (inserts with
`parent_task` set), `create_task_without_hours` (likewise) and `make_story()`
(always sets `issue`) all declare a source, so all three flags were deleted.
In particular the gate no longer consults the generic
`doc.flags.ignore_permissions`, which was never a safe money-gate signal.
(`custom/issue.py` still sets `via_issue_mapping` — `custom/task.py`'s
`validate_work_item_type_permission` uses it for an unrelated purpose.)

## 5. Task Split ↔ generated Task — two-way sync
No new sync machinery. `is_billable` joins `expected_hours` and `ecd` in the
two functions that already keep those two in step (`custom/task.py`):

- `sync_split_row_edits_to_generated_task` — a row edit pushes to the Task.
- `sync_expected_hours_to_split_row` — a Task edit pulls back to the row.

Both push with a raw `frappe.db.set_value`, which skips `validate()` and so
bypasses the clamp. These two are the **only** sanctioned raw writes to a
billable flag (the invariant is stated in a comment above
`sync_split_row_edits_to_generated_task`), and the row → Task direction needs
`validate_split_row_unbilling` (§3) to stand in for the `validate()` it skips.
Any new raw write to `Task.custom_is_billable` or `Task Split.is_billable`
must name the guard that covers it, or go through `doc.save()`.

## 6. Timesheet — forced from the Task, locked in the Desk
**Forcing the value.** `custom/timesheet.py:force_is_billable_from_task`,
hooked on Timesheet's `before_validate`. For every `time_logs` row that has a
`task`, it overwrites `row.is_billable` with that Task's
`custom_is_billable`. Rows with no task (plain activity logging) are left
alone.

`before_validate` is required, not stylistic: Frappe composes `doc_event`
handlers to run *after* the controller's own method
(`frappe/model/document.py:compose`), so a `validate` hook would fire after
core `Timesheet.validate()` has already run `calculate_hours` →
`update_billing_hours` — the corrected flag would never reach the billing
computation. `before_validate` runs before the controller entirely.

**Locking the field.** A Property Setter on `Timesheet Detail.is_billable`
sets `read_only_depends_on: "eval:doc.task"` (`install.py:set_timesheet_detail_billable_readonly`).
`read_only_depends_on` rather than a flat `read_only`, so a task-less activity
row keeps its manual checkbox — a flat lock would be a regression for anyone
logging non-task time.

**A billing mistake is fixed on the Task, not the Timesheet.** Core marks
`Timesheet Detail.is_billable` `allow_on_submit`, so before this feature a
billing mistake could be corrected in place on an already-submitted
Timesheet. Under this design it cannot: the field is forced from the Task on
every `before_validate`, and the Desk lock makes the cell read-only whenever
a task is set. The fix is to correct the Task's `custom_is_billable` and
amend the Timesheet — not to edit the row directly. This trade-off (over the
alternative of a default-plus-clamp that would still allow a per-row
override) was chosen deliberately: billing is a decision made upstream on the
work item, never per time entry.

No billing arithmetic is added anywhere — core already does
`if not ts_detail.is_billable: billing_rate = 0.0`, so `billing_hours` /
`base_billing_amount` / `total_billable_hours` and the existing
`Task.total_billing_amount` rollup all follow from the corrected flag with no
further code.

## 7. Existing data — no backfill
`custom_is_billable` defaults to `0` everywhere and there is no patch to
backfill it. Every Project, Issue, Task and Task Split row that existed
before 2026-08-03 started non-billable. A consequence accepted explicitly:
any draft Timesheet row that was marked billable against a Task before this
feature landed gets force-unchecked the next time that Timesheet is saved,
because no Task carries the flag yet. Submitted Timesheets are untouched —
they never re-run `validate`.

## Where the code lives
```
sigzenjira/custom/custom_fields.py         — the three Custom Field definitions (Project, Issue, Task)
sigzenjira/sigzenjira/doctype/task_split/task_split.json  — is_billable field + field_order entry
sigzenjira/custom/billable.py              — clamp helpers, permission validator, per-doctype entry points
sigzenjira/custom/task.py                  — generate_tasks_from_split, create_task_without_hours,
                                              sync_split_row_edits_to_generated_task, sync_expected_hours_to_split_row
sigzenjira/custom/issue.py                 — make_story copies the flag
sigzenjira/custom/timesheet.py             — force_is_billable_from_task
sigzenjira/install.py                      — sync_custom_fields, set_timesheet_detail_billable_readonly
sigzenjira/hooks.py                        — widened fixture filters; Project/Issue doc_events; Task validate
                                              entries; Timesheet before_validate
sigzenjira/public/js/{issue,task}.js       — default-on-source-change handlers, Task Split row-add handler
sigzenjira/tests/test_billable.py          — field/clamp/permission/propagation/timesheet coverage
```

## How it was verified
`sigzenjira/tests/test_billable.py` covers: the fields exist and default to
`0`; the upward clamp for Task-under-Task, Story-under-Epic,
Epic-under-Project, Issue-under-Project, and the post-delivery-support case
(Story clamped against its Issue, not just its Project); a billable parent
allowing mixed billable/non-billable children; the split-row upward clamp;
the downward clamp for Task/Project/Issue with a billable dependant, that a
Story and its own not-yet-generated rows can be unbilled together in one save,
and that unticking a row whose generated Task still has a billable Sub-task
throws (then succeeds once that Sub-task is unbilled); the permission gate
blocking a non-privileged flag change, a non-privileged split-row flip and a
non-privileged split-row *add*, while allowing an unrelated field edit and
allowing a privileged change; the new-doc rule in both directions — an
Employee may create a billable Sub-task under a billable Task, but may not
invent a billable `Project` (a doc with no declared source); `make_story`
copying both a billable and an unbilled Issue's flag onto the Story; the Task
Split ↔ Task two-way sync in both directions; `create_task_without_hours`
carrying a row's flag; and the Timesheet force in both directions plus the
read-only Property Setter.

The full `sigzenjira` suite (`bench --site mysite.in run-tests --app
sigzenjira --skip-before-tests`) was run after this feature was complete;
every failure found was independently reproduced against the pre-billable
commit this branch started from, confirming none were introduced by this
work.
