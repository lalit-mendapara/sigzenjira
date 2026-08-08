// Overrides core ERPNext's parent_task query (task.js) for our Epic/Story/Task/
// Sub-task hierarchy. Loaded after core's onload handler (this app loads after
// erpnext), so this frm.set_query call wins.
// Keep in sync with WORK_ITEM_TYPE_PRIVILEGED_ROLES in events/task.py - this
// only narrows the Desk dropdown for a better UX (Employees don't see
// options they can't use); the actual restriction is enforced server-side
// in validate_work_item_type_permission since a client-side check alone
// isn't real permission enforcement.
const WORK_ITEM_TYPE_PRIVILEGED_ROLES = [
	"Director",
	"Product Owner",
	"Projects Manager",
	"System Manager",
];

// Mirrors the custom_task_work_item_type Select options in custom_field.py -
// needed verbatim to put the dropdown back after narrowing it to Sub-task.
const WORK_ITEM_TYPE_OPTIONS = "\nEpic\nStory\nTask\nSub-task";

// A privileged role grants this org-wide; the per-Project "Set Work Item Type"
// flag on Project User grants the same thing for one Project. Mirrors
// validate_work_item_type_permission (events/task.py). The role half is
// synchronous, the Project half needs a server round trip - cached per project
// on the form so a refresh or a re-picked project doesn't re-ask the same
// question.
function can_set_work_item_type(frm) {
	if (WORK_ITEM_TYPE_PRIVILEGED_ROLES.some((role) => frappe.user_roles.includes(role))) {
		return Promise.resolve(true);
	}
	if (frm.__work_item_type_perm_project === frm.doc.project) {
		return Promise.resolve(frm.__work_item_type_perm);
	}
	return frappe
		.call({
			method: "sigzenjira.events.task.get_task_split_permissions",
			args: { project: frm.doc.project },
		})
		.then(function (r) {
			frm.__work_item_type_perm_project = frm.doc.project;
			frm.__work_item_type_perm = !!(r.message && r.message.set_work_item_type);
			return frm.__work_item_type_perm;
		});
}

// Only narrow the dropdown on a NEW doc - narrowing it on an EXISTING
// Epic/Story/Task would drop "Epic"/"Story"/"Task" from the options list
// entirely, and a Select field can't render a current value that isn't in its
// options - the field would look blank/unreadable to a non-privileged user
// even though the real value is intact in the DB. Everyone can always READ the
// current classification; only who can SET it to something new is restricted.
function narrow_work_item_type(frm) {
	if (!frm.is_new()) {
		return;
	}
	can_set_work_item_type(frm).then(function (allowed) {
		frm.set_df_property(
			"custom_task_work_item_type",
			"options",
			allowed ? WORK_ITEM_TYPE_OPTIONS : "Sub-task"
		);
		if (!allowed && !frm.doc.custom_task_work_item_type) {
			frm.set_value("custom_task_work_item_type", "Sub-task");
		}
	});
}

// Nearest child level for each Work Item Type - null means no lower level
// exists (Sub-task is the bottom of the tree). Mirrors EXPECTED_PARENT_TYPE
// in events/task.py, inverted.
const CHILD_WORK_ITEM_TYPE = {
	Epic: "Story",
	Story: "Task",
	Task: "Sub-task",
	"Sub-task": null,
};

// Mirrors EMPLOYEE_STORY_LOCKED_EXCEPTIONS in events/task.py - this only
// makes the UI match what the server actually enforces
// (validate_employee_story_field_restriction); it isn't the real boundary.
const EMPLOYEE_STORY_EDITABLE_FIELDS = new Set([
	"custom_task_task_template",
	"custom_task_task_split",
]);

// Mirrors the Task Status Select options (erpnext task.json) - Overdue/
// Template/Cancelled are intentionally left unstyled, only the 4 the user
// asked for get a colour.
const TASK_SPLIT_STATUS_CLASS = {
	Open: "task-split-status-open",
	Working: "task-split-status-progress",
	"Pending Review": "task-split-status-review",
	Completed: "task-split-status-done",
};

function inject_task_split_status_css() {
	if (document.getElementById("task-split-status-style")) {
		return;
	}
	$(`<style id="task-split-status-style">
		.task-split-status-open { background-color: rgba(150, 150, 150, 0.25) !important; }
		.task-split-status-progress { background-color: rgba(0, 123, 255, 0.2) !important; }
		.task-split-status-review { background-color: rgba(255, 193, 7, 0.25) !important; }
		.task-split-status-done { background-color: rgba(40, 167, 69, 0.2) !important; }
		.task-split-linkable .static-area { cursor: pointer; text-decoration: underline; }
	</style>`).appendTo("head");
}

// Colours the Task Item cell by the generated Task's status, and makes it
// open that Task's form on click instead of the grid's default click-to-edit
// (task_item is already read_only once generated_task is set, via
// read_only_depends_on on the Task Split doctype - editing it inline was
// never useful for a generated row anyway).
function style_task_split_row(grid_row, status_map) {
	const column = grid_row.columns && grid_row.columns.task_item;
	if (!column) {
		return;
	}
	const row = grid_row.doc;

	Object.values(TASK_SPLIT_STATUS_CLASS).forEach((cls) => column.removeClass(cls));
	const status_class = TASK_SPLIT_STATUS_CLASS[status_map[row.generated_task]];
	if (status_class) {
		column.addClass(status_class);
	}

	column.toggleClass("task-split-linkable", Boolean(row.generated_task));
	if (row.generated_task) {
		column.off("click").on("click", function (e) {
			e.preventDefault();
			e.stopImmediatePropagation();
			frappe.set_route("Form", "Task", row.generated_task);
		});
	}
}

function refresh_task_split_status_colors(frm) {
	if (frm.doc.custom_task_work_item_type !== "Story") {
		return;
	}
	const grid = frm.fields_dict.custom_task_task_split && frm.fields_dict.custom_task_task_split.grid;
	if (!grid) {
		return;
	}

	const generated_tasks = (frm.doc.custom_task_task_split || [])
		.map((row) => row.generated_task)
		.filter(Boolean);
	if (!generated_tasks.length) {
		return;
	}

	frappe.db
		.get_list("Task", {
			filters: { name: ["in", generated_tasks] },
			fields: ["name", "status"],
			limit: 0,
		})
		.then((tasks) => {
			frm.__task_split_status_map = {};
			tasks.forEach((task) => (frm.__task_split_status_map[task.name] = task.status));
			grid.grid_rows.forEach((grid_row) =>
				style_task_split_row(grid_row, frm.__task_split_status_map)
			);
		});
}

function lock_task_split_columns(frm) {
	if (frm.is_new() || frm.doc.custom_task_work_item_type !== "Story") {
		return;
	}
	frappe.call({
		method: "sigzenjira.events.task.get_task_split_permissions",
		args: { project: frm.doc.project },
		callback: function (r) {
			frm.__task_split_perms = r.message || { allocate_hours: false, assign_users: false };
			frm.fields_dict.custom_task_task_split.grid.update_docfield_property(
				"expected_hours",
				"read_only",
				frm.__task_split_perms.allocate_hours ? 0 : 1
			);
			frm.fields_dict.custom_task_task_split.grid.refresh();
			// Same gate on the Story's own budget - rollup_story_expected_time
			// enforces it server-side either way.
			frm.set_df_property(
				"expected_time",
				"read_only",
				frm.__task_split_perms.allocate_hours ? 0 : 1
			);
		},
	});
}

function add_create_child_button(frm, child_type) {
	frm.add_custom_button(__("Create {0}", [child_type]), function () {
		frappe.new_doc("Task", {
			parent_task: frm.doc.name,
			custom_task_work_item_type: child_type,
			project: frm.doc.project,
		});
	});
}

function lock_story_to_template_only(frm) {
	if (frm.is_new() || frm.doc.custom_task_work_item_type !== "Story") {
		return;
	}
	can_set_work_item_type(frm).then(function (allowed) {
		if (allowed) {
			return;
		}
		frm.meta.fields.forEach((df) => {
			if (!EMPLOYEE_STORY_EDITABLE_FIELDS.has(df.fieldname)) {
				frm.set_df_property(df.fieldname, "read_only", 1);
			}
		});
		// The split grid stays writable so they can break their own work down,
		// but rows only go one way - removing one deletes the generated Task
		// and its Sub-tasks (validate_task_split_row_deletion throws server-side).
		frm.fields_dict.custom_task_task_split.grid.df.cannot_delete_rows = 1;
		frm.refresh_fields();
	});
}

function get_task_template_items(name) {
	return frappe
		.xcall("frappe.client.get", { doctype: "Task Template", name })
		.then((doc) => doc.tasks || []);
}

// Swapping to a different template drops the rows the old one put there, so the
// grid shows one template's items and not both. Rows that already generated a
// Task are kept (deleting one would orphan that Task), and so is anything the PM
// typed by hand - only task_items the old template contributed go.
function drop_previous_template_rows(frm, prev_items) {
	const stale = new Set(prev_items.map((row) => row.task_item));
	const keep = (frm.doc.custom_task_task_split || []).filter(
		(row) => row.generated_task || !stale.has(row.task_item)
	);
	const removed = (frm.doc.custom_task_task_split || []).length - keep.length;
	frm.doc.custom_task_task_split = keep;
	keep.forEach((row, i) => (row.idx = i + 1));
	return removed;
}

// Additive within one template. A row that already generated a Task can't be
// thrown away and rebuilt (the Task would be orphaned), and a row a PM
// deliberately dropped shouldn't silently come back on an unrelated save - so
// only the template items with no matching task_item in the grid get appended.
// That makes re-applying the template the way back from a deleted Task or a
// hand-removed row, without touching anything already in flight.
function apply_task_template(frm) {
	const template = frm.doc.custom_task_task_template;
	const previous = frm.__applied_task_template;
	if (!template) {
		frm.__applied_task_template = null;
		return;
	}

	const previous_items =
		previous && previous !== template
			? get_task_template_items(previous)
			: Promise.resolve([]);

	Promise.all([get_task_template_items(template), previous_items]).then(function (result) {
		const [items, prev_items] = result;
		const removed = prev_items.length ? drop_previous_template_rows(frm, prev_items) : 0;

		// "Empty" means no row has real content yet - a blank row from
		// clicking "Add Row" counts as empty, so a first apply clears it
		// out rather than leaving a row that fails task_item's reqd.
		const existing = new Set(
			(frm.doc.custom_task_task_split || []).map((row) => row.task_item).filter(Boolean)
		);
		if (!existing.size) {
			frm.clear_table("custom_task_task_split");
		}

		let added = 0;
		items.forEach(function (row) {
			if (existing.has(row.task_item)) {
				return;
			}
			const split_row = frm.add_child("custom_task_task_split");
			split_row.task_item = row.task_item;
			split_row.description = row.description;
			// Seed Billable the same way the grid's Add Row does. Not
			// automatic: custom_task_split_add only fires from
			// Grid.add_new_row, and frappe.model.add_child (what
			// frm.add_child calls) triggers nothing - so without this a
			// template applied to a billable Story would produce unticked
			// rows and every Task it generated would silently not bill.
			split_row.is_billable = cint(frm.doc.custom_task_is_billable);
			added += 1;
		});

		frm.__applied_task_template = template;
		frm.refresh_field("custom_task_task_split");
		frappe.show_alert(
			added || removed
				? __("Added {0} row(s) from {1}, removed {2} from the previous template.", [
						added,
						template,
						removed,
				  ])
				: __("Task Split already has every item from {0}.", [template])
		);
	});
}

// Mirrors issue.js. A Task's default comes from its parent_task if it has one,
// otherwise its project - the same precedence the server's PARENT_SOURCES uses,
// except the server checks ALL sources while this only needs a starting value.
function seed_billable_from_source(frm) {
	// The Billable fieldname carries its doctype (custom_<doctype>_<name>), so it
	// travels with the source rather than being one shared constant - mirrors
	// BILLABLE_FIELDS in events/billable.py.
	const source = frm.doc.parent_task
		? { doctype: "Task", name: frm.doc.parent_task, field: "custom_task_is_billable" }
		: frm.doc.project
		? { doctype: "Project", name: frm.doc.project, field: "custom_project_is_billable" }
		: null;

	if (!source) {
		return;
	}

	frappe.db.get_value(source.doctype, source.name, source.field).then((r) => {
		frm.set_value("custom_task_is_billable", cint(r.message && r.message[source.field]));
	});
}

frappe.ui.form.on("Task", {
	onload_post_render(frm) {
		if (frm.is_new()) {
			seed_billable_from_source(frm);
		}
	},

	parent_task(frm) {
		// Only while new. On a saved document this would silently overwrite a
		// deliberate choice - a non-billable Task under a billable Story is
		// legitimate, and reparenting it must not quietly start billing it.
		if (frm.is_new()) {
			seed_billable_from_source(frm);
		}
	},

	project(frm) {
		// Same reasoning as parent_task above.
		if (frm.is_new()) {
			seed_billable_from_source(frm);
			// The "Set Work Item Type" grant is per-Project, so the answer
			// only exists once a Project is picked - and changes with it.
			narrow_work_item_type(frm);
		}
	},

	onload: function (frm) {
		inject_task_split_status_css();

		// grid-row-render fires per-row on every grid render/refresh (initial
		// load, add row, frm.reload_doc after "Create Task", etc.) - bind once
		// here rather than re-binding inside refresh.
		$(frm.wrapper)
			.off("grid-row-render.task_split_status")
			.on("grid-row-render.task_split_status", function (e, grid_row) {
				if (
					grid_row.grid &&
					grid_row.grid.df &&
					grid_row.grid.df.fieldname === "custom_task_task_split"
				) {
					style_task_split_row(grid_row, frm.__task_split_status_map || {});
				}
			});

		narrow_work_item_type(frm);

		frm.set_query("parent_task", function () {
			const expected_parent_type = {
				Epic: null,
				Story: "Epic",
				Task: "Story",
				"Sub-task": "Task",
			}[frm.doc.custom_task_work_item_type];

			if (!expected_parent_type) {
				// Epic (never has a parent) or type not chosen yet: no valid options.
				return { filters: { name: ["in", []] } };
			}

			return {
				filters: {
					custom_task_work_item_type: expected_parent_type,
					name: ["!=", frm.doc.name],
				},
			};
		});
	},

	refresh: function (frm) {
		// Mirrors validate_parent_task_is_immutable (events/task.py) - a parent
		// that is already set is frozen, so show it as read-only rather than
		// letting someone re-pick and get thrown at on save.
		const parent_locked = !frm.is_new() && !!frm.doc.parent_task;
		frm.set_df_property("parent_task", "read_only", parent_locked ? 1 : 0);

		// A Story created from an Issue (events/issue.py:make_story) copies the
		// Issue's description - editing it here would silently drift from the
		// ticket it came from, so it stays read-only.
		frm.set_df_property(
			"description",
			"read_only",
			frm.doc.custom_task_work_item_type === "Story" && frm.doc.issue ? 1 : 0
		);

		// Baseline for apply_task_template's swap cleanup: the template the grid's
		// rows actually came from. refresh fires on load and after save, so this
		// tracks the saved value and never fights an in-progress change.
		frm.__applied_task_template = frm.doc.custom_task_task_template;

		lock_story_to_template_only(frm);
		lock_task_split_columns(frm);
		refresh_task_split_status_colors(frm);

		// Re-picking the value a Link field already holds fires no change
		// event, so custom_task_task_template alone gives a Story that lost a row
		// (deleted generated Task, row removed by hand) no way back to the
		// template's full list. This is that way back - and being an explicit
		// click, it can't resurrect a dropped row behind the PM's back.
		if (frm.doc.custom_task_work_item_type === "Story" && frm.doc.custom_task_task_template) {
			frm.add_custom_button(__("Apply Task Template"), () => apply_task_template(frm));
		}

		// Only on an already-saved item - a not-yet-created Epic has no
		// name yet to link a new child's parent_task to.
		if (frm.is_new()) {
			return;
		}

		const child_type = CHILD_WORK_ITEM_TYPE[frm.doc.custom_task_work_item_type];
		if (!child_type) {
			return;
		}

		// A Story gets this button too: the split grid is cramped for typing a
		// whole Task, so "Create Task" opens the full form instead, and
		// create_split_row_for_manual_task (events/task.py) mirrors the saved
		// Task back into the grid. The budget check isn't skipped - the mirrored
		// row goes through rollup_story_expected_time and
		// validate_task_split_expected_hours_permission like any other row.
		if (!frappe.model.can_create("Task")) {
			return;
		}

		// Sub-task is open to everyone (per validate_work_item_type_permission,
		// events/task.py); Epic/Story/Task classification is gated - only show
		// the button if this user could actually save that type.
		if (child_type === "Sub-task") {
			add_create_child_button(frm, child_type);
			return;
		}
		can_set_work_item_type(frm).then(function (allowed) {
			if (allowed) {
				add_create_child_button(frm, child_type);
			}
		});
	},

	custom_task_task_template: apply_task_template,
});

// Task Split is a child table (istable=1) - it never renders as its own
// Desk form, so a .js file under its own doctype folder never loads. Child
// grid field events have to be registered from a script that DOES load, i.e.
// the parent's - this file already loads on every Task/Story form via the
// doctype_js hook, so registering the child doctype's events here works.
frappe.ui.form.on("Task Split", {
	// A new row starts wherever the Story is - the server clamp then makes a
	// billable row under a non-billable Story impossible anyway. Grid row-add
	// events fire with the CHILD doctype (frappe/form/grid.js:
	// `this.frm.script_manager.trigger(this.df.fieldname + "_add", d.doctype, d.name)`
	// where d is the new child row), so this belongs on "Task Split", not "Task"
	// - erpnext's own stock_entry.js registers items_add the same way, on
	// "Stock Entry Detail". Unguarded by frm.is_new(): a split row is always
	// new the moment it's added, even to an already-saved Story.
	custom_task_split_add: function (frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "is_billable", cint(frm.doc.custom_task_is_billable));
	},

	create_action: function (frm, cdt, cdn) {
		// Either flag - mirrors create_task_without_hours (events/task.py).
		const perms = frm.__task_split_perms;
		if (perms && !(perms.allocate_hours || perms.set_work_item_type)) {
			frappe.msgprint(
				__(
					"Only a user with Allocate Hours or Set Work Item Type access on this Project can create a Task from this row."
				)
			);
			return;
		}

		const row = locals[cdt][cdn];
		if (!row.task_item) {
			frappe.msgprint(__("Fill in Task Item before creating a Task from this row."));
			return;
		}

		// The row only exists in the browser until the Story is saved -
		// create_task_without_hours looks it up by name in the DB, so an
		// unsaved Story (or a row just added to a saved one) would throw
		// "Task Split row not found." Save first, then re-read the row: save
		// replaces the client-side rows, so the real name comes from idx.
		const needs_save = frm.is_new() || row.__islocal || frm.is_dirty();

		frappe.confirm(
			needs_save
				? __(
						"Save this Story and create a Task for {0} without an Expected Hours budget?",
						[row.task_item]
				  )
				: __("Create a Task for {0} without an Expected Hours budget?", [row.task_item]),
			function () {
				const ready = needs_save ? frm.save() : Promise.resolve();
				ready.then(function () {
					const saved_row = needs_save
						? (frm.doc.custom_task_task_split || [])[row.idx - 1]
						: row;
					// Saving with expected_hours filled already generates the
					// Task via generate_tasks_from_split - nothing left to do.
					if (!saved_row || saved_row.generated_task) {
						return;
					}
					// frm.save() resolves even when the SERVER rejected the save
					// (form.js after_save calls resolve() whether or not r.exc is
					// set), so a failed save lands here with the row still local -
					// sending that name got "Task Split row not found." on top of
					// the real error. The save's own error dialog is the message
					// that matters; just stop.
					if (saved_row.__islocal || !saved_row.name) {
						return;
					}
					frappe.call({
						method: "sigzenjira.events.task.create_task_without_hours",
						args: { row_name: saved_row.name },
						freeze: true,
						callback: function () {
							frm.reload_doc();
						},
					});
				});
			}
		);
	},

	assign_action: function (frm, cdt, cdn) {
		if (frm.__task_split_perms && !frm.__task_split_perms.assign_users) {
			frappe.msgprint(__("You dont have permission to assign users from task-split "));
			return;
		}

		const row = locals[cdt][cdn];
		// Filled from the server before the dialog is shown - the picker only
		// ever offers this Project's team.
		let project_users = [];

		const dialog = new frappe.ui.Dialog({
			title: __("Assign"),
			fields: [
				{
					fieldname: "assign_to_me",
					fieldtype: "Check",
					label: __("Assign to me"),
					onchange: function () {
						const users = dialog.get_value("users") || [];
						const me = frappe.session.user;
						dialog.set_value(
							"users",
							dialog.get_value("assign_to_me")
								? [...new Set([...users, me])]
								: users.filter((user) => user !== me)
						);
					},
				},
				{
					fieldname: "users",
					fieldtype: "MultiSelectPills",
					label: __("Users"),
					get_data: function (txt) {
						const query = (txt || "").toLowerCase();
						return project_users.filter(
							(user) =>
								user.value.toLowerCase().includes(query) ||
								(user.description || "").toLowerCase().includes(query)
						);
					},
				},
			],
			primary_action_label: __("Update"),
			primary_action: function (values) {
				if (row.generated_task) {
					frappe.call({
						method: "sigzenjira.events.task.set_split_row_assignees",
						args: { row_name: row.name, users: values.users },
						callback: function () {
							dialog.hide();
							frm.reload_doc();
						},
					});
				} else {
					// No Task yet - stage the picks on the row itself.
					// generate_tasks_from_split (events/task.py) applies them as
					// real assignment the moment the Story save creates the Task.
					// The visible Assign column is otherwise only ever written by
					// the real-assignment sync (events/todo.py), which has nothing
					// to sync yet - fill it in here too, purely so the pick shows
					// up immediately instead of looking like it did nothing.
					const users = values.users || [];
					frappe.model.set_value(
						cdt,
						cdn,
						"pending_assign_users",
						JSON.stringify(users)
					);
					frappe.model.set_value(
						cdt,
						cdn,
						"assign",
						users.map((user) => frappe.user_info(user).fullname || user).join(", ")
					);
					dialog.hide();
					frm.dirty();
				}
			},
		});

		const show_dialog = (selected) => {
			frappe.call({
				method: "sigzenjira.events.task.get_project_assignable_users",
				args: { project: frm.doc.project },
				callback: function (r) {
					project_users = r.message || [];
					dialog.set_value("users", selected);
					dialog.set_value("assign_to_me", selected.includes(frappe.session.user) ? 1 : 0);
					dialog.show();
				},
			});
		};

		if (row.generated_task) {
			frappe.db.get_value("Task", row.generated_task, "_assign").then((r) => {
				show_dialog(r.message._assign ? JSON.parse(r.message._assign) : []);
			});
		} else {
			show_dialog(row.pending_assign_users ? JSON.parse(row.pending_assign_users) : []);
		}
	},
});
