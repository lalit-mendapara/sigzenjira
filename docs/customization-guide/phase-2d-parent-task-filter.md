# Phase 2d — Filter Parent Task by expected work item type

Two things caught during manual testing:

1. **Unchecked (not-yet-a-group) Stories don't show up when picking a
   Parent Task.** Confirmed why: core ERPNext's own `task.js`
   (`apps/erpnext/erpnext/projects/doctype/task/task.js`) hardcodes
   `frm.set_query("parent_task", { is_group: 1, ... })`. Combined with Phase
   2c's lazy `is_group` (starts unchecked until a real child exists), that
   core filter excludes exactly the freshly-created, still-childless
   Epics/Stories/Tasks a user would want to attach the *first* child to —
   a chicken-and-egg gap in the stock UI, not something our server-side
   logic caused.

2. **Parent Task picker should only offer the correct type** — selecting
   `custom_work_item_type = Task` should filter the picker down to Stories
   only (per the same `EXPECTED_PARENT_TYPE` mapping from Phase 2), not every
   Task record.

## The fix
Can't edit `apps/erpnext` to change that hardcoded filter. The correct way to
extend/override a core doctype's client-side form script from a custom app is
the `doctype_js` hook — it loads an additional JS file on top of the core
one, and because apps load in the order listed in `sites/apps.txt`
(`frappe, erpnext, sigzenjira` — confirmed by reading the file), sigzenjira's
script runs *after* erpnext's `onload` handler. Calling `frm.set_query`
again for the same fieldname simply replaces the previous query function, so
ours wins.

```python
# hooks.py
doctype_js = {"Task": "public/js/task.js"}
```

```js
// sigzenjira/public/js/task.js
frappe.ui.form.on("Task", {
  onload: function (frm) {
    frm.set_query("parent_task", function () {
      const expected_parent_type = {
        Epic: null,
        Story: "Epic",
        Task: "Story",
        "Sub-task": "Task",
      }[frm.doc.custom_work_item_type];

      if (!expected_parent_type) {
        return { filters: { name: ["in", []] } }; // Epic, or type not chosen yet
      }
      return {
        filters: { custom_work_item_type: expected_parent_type, name: ["!=", frm.doc.name] },
      };
    });
  },
});
```

No `is_group: 1` in our replacement filter — that's the whole point, it was
the thing blocking childless containers from being selectable in the first
place. The query function reads `frm.doc.custom_work_item_type` live, so it
picks up whatever the user has currently selected each time they open the
Parent Task dropdown — no extra field-change listener needed.

## Where the code lives
```
sigzenjira/hooks.py            — doctype_js wiring
sigzenjira/public/js/task.js   — the overriding frm.set_query
```

After adding/changing a `public/js` file, `bench build --app sigzenjira` +
`bench --site mysite.in clear-cache` are needed to pick it up (esbuild just
symlinks `public/` for doctype_js files — no bundling step actually changes
anything, but the cache clear is what makes Desk fetch the updated hooks).

## Not verifiable headlessly
This is pure client-side behavior (a Desk form's Link-field search), so it
can't be checked from a backend script the way Phases 1–2c were. Confirmed:
hook resolves (`frappe.get_hooks("doctype_js")` returns the file), the JS
file is valid (`node --check`) and reachable at
`sites/assets/sigzenjira/js/task.js`, and app load order in `apps.txt` puts
sigzenjira after erpnext. Needs a real browser check — see test steps below.
