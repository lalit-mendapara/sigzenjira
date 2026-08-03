# Phase 2b — Show Work Item Type when searching Parent Task

Not in the original plan — added because picking a Parent Task by its bare
`TASK-2026-00003` ID (or subject alone) is useless once there are dozens of
tasks; you can't tell an Epic from a Story from the picker.

## First attempt was wrong, reverted
Initial version added a hidden computed field (`custom_task_title`,
`f"{subject} - {work_item_type}"`) and pointed the doctype's `title_field` at
it. That changes what Task's name/title looks like *everywhere* it's
referenced (list views, reports, every Link field) and adds a field that has
to be kept in sync on every save — more than what was actually asked for.
Reverted: deleted the `Custom Field`, dropped the column, deleted the
`title_field` / `show_title_field_in_link` property setters.

## What was actually wanted
Just: when searching the `parent_task` field, see the work item type next to
each match. That's a narrower, purely search/display concern — it doesn't
need a new field or a change to Task's title.

## The native Frappe feature for this
A DocType has a `search_fields` property (comma-separated fieldnames). Core
Frappe's link search (`frappe/desk/search.py`, `search_widget`) includes
those fields as extra columns in the query and displays them as description
text under each match in the Link field's dropdown — this is exactly what
"show X while searching a Link field" means in Frappe, no custom code
involved.

Task's `search_fields` was `subject` (core default). Changed via a
doctype-level Property Setter to `subject,custom_work_item_type`:

```python
make_property_setter(
    "Task", None, "search_fields", "subject,custom_work_item_type", "Data", for_doctype=True
)
```

Now typing into the `parent_task` field on any Task shows each match's
subject *and* its Work Item Type underneath, without adding, hiding, or
computing anything new.

## Where the code lives
```
sigzenjira/install.py   — set_task_search_fields()
sigzenjira/fixtures/property_setter.json   — re-applied on every migrate
```

## Verified
`frappe.get_meta("Task").search_fields == "subject,custom_work_item_type"`
after migrate; the 4 existing Task records and their `custom_work_item_type`
/ `custom_extra_hours` values were untouched by the revert.
