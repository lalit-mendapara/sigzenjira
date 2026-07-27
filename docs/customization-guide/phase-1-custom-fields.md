# Phase 1 — Custom Fields on Task

## Goal
Add two fields to the core ERPNext `Task` doctype: `custom_work_item_type` (classifies a
Task as Epic/Story/Task/Sub-task) and `custom_extra_hours` (tracks approved extra hours,
filled in later by Phase 5). Do this **without editing `apps/erpnext` directly** —
that's a pinned git submodule; editing it there gets silently wiped the next time
someone re-pins/updates the submodule, and it's explicitly against this repo's rules.

## The ERPNext-correct way to add a field to a core doctype
Frappe gives you two ways to extend a standard doctype's schema from a custom app:

1. **Customize Form** (Desk UI) → creates a `Custom Field` / `Property Setter`
   database record. Frappe overlays these on top of the standard doctype at
   runtime. Nothing in `apps/erpnext` changes.
2. **`create_custom_fields()`** (Python API) → does the same thing
   programmatically, which is what you want when the field needs to ship with
   the app (installs, other sites, version control) instead of being a one-off
   click in the UI.

We use #2, because the field needs to exist automatically on every site that
installs `sigzenjira`, not just on `mysite.in` where someone happened to click
around in the UI.

## Where the code lives
```
sigzenjira/custom/custom_fields.py   — the field definitions (a plain dict)
sigzenjira/install.py                — after_install hook, runs create_custom_fields()
sigzenjira/patches/v0_0/             — same calls, for sites where sigzenjira is
                                        ALREADY installed (after_install only
                                        fires once, on first install)
sigzenjira/hooks.py                  — wires after_install + patches.txt entry
                                        + `fixtures` so the resulting Custom Field
                                        records export to version control
```

## Why the `custom_` prefix
Every fieldname here starts with `custom_` — deliberately, not because Frappe
requires it. `Task`'s own core fields never use that prefix, so a `custom_`
prefix makes it instantly obvious, everywhere (form, reports, DB schema, code)
which fields belong to `sigzenjira` and which come from ERPNext. Frappe's own
"Customize Form" UI defaults to the same prefix for the same reason when you
add a field through the Desk.

One consequence worth knowing: a Custom Field created via `create_custom_fields()`
is marked `is_system_generated = 1`, which blocks Frappe's own field-rename tool
(`rename_fieldname`, the one "Customize Form" calls in the UI) — it's meant to stop
someone accidentally renaming a field a developer shipped. If you ever need to
rename one of these fields later, do what its rename does under the hood
manually: `frappe.db.rename_column(doctype, old, new)` (keeps the data), then
update the `Custom Field.fieldname` value and any `insert_after` references that
pointed at the old name, then update this app's code to match.

`fixtures` in `hooks.py` matters: without it, the Custom Field rows only exist in
the database. `bench export-fixtures` writes them to a JSON file inside the app,
so a fresh `bench install-app sigzenjira` on another machine recreates the exact
same fields from git history, not from someone remembering to click through the
UI again.

## Field specs
- **`custom_work_item_type`** — Select, options `Epic / Story / Task / Sub-task`,
  mandatory, placed right after `subject`.
- **`custom_extra_hours`** — Float, default `0`, `read_only: 1` (Desk UI can't edit it —
  only Phase 5's approval logic will, via `db_set`), `no_copy: 1` (doesn't get
  copied when a Task is duplicated).

## A real Frappe gotcha we hit
A mandatory (`reqd: 1`) Select field **with no explicit default** does not
behave the way you'd expect. Frappe's `get_static_default_value()`
(`frappe/model/create_new.py`) silently defaults *any* Select field to its
*first listed option* before mandatory-field validation ever runs — so leaving
the field blank on the form doesn't throw an error, it just quietly saves as
whatever option happens to be listed first.

Fix: give the Select field a **leading blank option** —
`options: "\nEpic\nStory\nTask\nSub-task"` instead of
`"Epic\nStory\nTask\nSub-task"`. Now "unselected" defaults to `""` (falsy),
so mandatory validation correctly catches it. This is a standard, widely-used
Frappe idiom for mandatory Select fields with no natural default value — not
something specific to this app.

## How it was verified
A throwaway test module (`sigzenjira/temp_test_phase1.py`, deleted after use —
never commit scratch test scripts like this) created Task records through
`frappe.get_doc(...).insert()` and checked:
- blank `custom_work_item_type` → `frappe.MandatoryError` raised, save blocked
- valid `custom_work_item_type` → saves, `custom_extra_hours` defaults to `0`
- `custom_extra_hours` carries `read_only` + `no_copy` in the doctype meta

Manually confirmed on the Desk UI by the project owner: blank Work Item Type
blocks save, Extra Hours renders greyed out at 0, both fields survive
`bench migrate`.
