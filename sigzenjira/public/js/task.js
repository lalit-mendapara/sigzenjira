// Overrides core ERPNext's parent_task query (task.js) for our Epic/Story/Task/
// Sub-task hierarchy. Loaded after core's onload handler (this app loads after
// erpnext), so this frm.set_query call wins.
// Keep in sync with WORK_ITEM_TYPE_PRIVILEGED_ROLES in custom/task.py - this
// only narrows the Desk dropdown for a better UX (Employees don't see
// options they can't use); the actual restriction is enforced server-side
// in validate_work_item_type_permission since a client-side check alone
// isn't real permission enforcement.
const WORK_ITEM_TYPE_PRIVILEGED_ROLES = ["Director", "Product Owner", "Projects Manager", "System Manager"];

// Nearest child level for each Work Item Type - null means no lower level
// exists (Sub-task is the bottom of the tree). Mirrors EXPECTED_PARENT_TYPE
// in custom/task.py, inverted.
const CHILD_WORK_ITEM_TYPE = {
	Epic: "Story",
	Story: "Task",
	Task: "Sub-task",
	"Sub-task": null,
};

// Mirrors EMPLOYEE_STORY_LOCKED_EXCEPTIONS in custom/task.py - this only
// makes the UI match what the server actually enforces
// (validate_employee_story_field_restriction); it isn't the real boundary.
const EMPLOYEE_STORY_EDITABLE_FIELDS = new Set(["custom_task_template"]);

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
	if (frm.doc.custom_work_item_type !== "Story") {
		return;
	}
	const grid = frm.fields_dict.custom_task_split && frm.fields_dict.custom_task_split.grid;
	if (!grid) {
		return;
	}

	const generated_tasks = (frm.doc.custom_task_split || []).map((row) => row.generated_task).filter(Boolean);
	if (!generated_tasks.length) {
		return;
	}

	frappe.db.get_list("Task", { filters: { name: ["in", generated_tasks] }, fields: ["name", "status"], limit: 0 }).then((tasks) => {
		frm.__task_split_status_map = {};
		tasks.forEach((task) => (frm.__task_split_status_map[task.name] = task.status));
		grid.grid_rows.forEach((grid_row) => style_task_split_row(grid_row, frm.__task_split_status_map));
	});
}

function lock_task_split_columns(frm) {
	if (frm.is_new() || frm.doc.custom_work_item_type !== "Story") {
		return;
	}
	frappe.call({
		method: "sigzenjira.custom.task.get_task_split_permissions",
		args: { project: frm.doc.project },
		callback: function (r) {
			frm.__task_split_perms = r.message || { allocate_hours: false, assign_users: false };
			frm.fields_dict.custom_task_split.grid.update_docfield_property(
				"expected_hours",
				"read_only",
				frm.__task_split_perms.allocate_hours ? 0 : 1
			);
			frm.fields_dict.custom_task_split.grid.refresh();
		},
	});
}

function lock_story_to_template_only(frm) {
	if (frm.is_new() || frm.doc.custom_work_item_type !== "Story") {
		return;
	}
	if (WORK_ITEM_TYPE_PRIVILEGED_ROLES.some((role) => frappe.user_roles.includes(role))) {
		return;
	}

	frm.meta.fields.forEach((df) => {
		if (!EMPLOYEE_STORY_EDITABLE_FIELDS.has(df.fieldname)) {
			frm.set_df_property(df.fieldname, "read_only", 1);
		}
	});
	frm.refresh_fields();
}

frappe.ui.form.on("Task", {
	onload: function (frm) {
		inject_task_split_status_css();

		// grid-row-render fires per-row on every grid render/refresh (initial
		// load, add row, frm.reload_doc after "Create Task", etc.) - bind once
		// here rather than re-binding inside refresh.
		$(frm.wrapper)
			.off("grid-row-render.task_split_status")
			.on("grid-row-render.task_split_status", function (e, grid_row) {
				if (grid_row.grid && grid_row.grid.df && grid_row.grid.df.fieldname === "custom_task_split") {
					style_task_split_row(grid_row, frm.__task_split_status_map || {});
				}
			});

		// Only narrow the dropdown on a NEW doc - narrowing it on an
		// EXISTING Epic/Story/Task would drop "Epic"/"Story"/"Task" from
		// the options list entirely, and a Select field can't render a
		// current value that isn't in its options - the field would look
		// blank/unreadable to a non-privileged role even though the real
		// value is intact in the DB. Everyone can always READ the current
		// classification; only who can SET it to something new is restricted.
		if (frm.is_new() && !WORK_ITEM_TYPE_PRIVILEGED_ROLES.some((role) => frappe.user_roles.includes(role))) {
			frm.set_df_property("custom_work_item_type", "options", "Sub-task");
			if (!frm.doc.custom_work_item_type) {
				frm.set_value("custom_work_item_type", "Sub-task");
			}
		}

		frm.set_query("parent_task", function () {
			const expected_parent_type = {
				Epic: null,
				Story: "Epic",
				Task: "Story",
				"Sub-task": "Task",
			}[frm.doc.custom_work_item_type];

			if (!expected_parent_type) {
				// Epic (never has a parent) or type not chosen yet: no valid options.
				return { filters: { name: ["in", []] } };
			}

			return {
				filters: {
					custom_work_item_type: expected_parent_type,
					name: ["!=", frm.doc.name],
				},
			};
		});
	},

	refresh: function (frm) {
		lock_story_to_template_only(frm);
		lock_task_split_columns(frm);
		refresh_task_split_status_colors(frm);

		// Only on an already-saved item - a not-yet-created Epic has no
		// name yet to link a new child's parent_task to.
		if (frm.is_new()) {
			return;
		}

		const child_type = CHILD_WORK_ITEM_TYPE[frm.doc.custom_work_item_type];
		if (!child_type) {
			return;
		}

		// Story's Tasks are only ever meant to come from custom_task_split
		// (generate_tasks_from_split, custom/task.py) - a manual "Create Task"
		// button here would let a PM add Tasks outside that budget-checked flow.
		if (frm.doc.custom_work_item_type === "Story") {
			return;
		}

		// Sub-task is open to everyone (per validate_work_item_type_permission,
		// custom/task.py); Epic/Story/Task classification is role-gated - only
		// show the button if this user could actually save that type.
		const can_create_child_type =
			child_type === "Sub-task" || WORK_ITEM_TYPE_PRIVILEGED_ROLES.some((role) => frappe.user_roles.includes(role));

		if (!can_create_child_type || !frappe.model.can_create("Task")) {
			return;
		}

		frm.add_custom_button(__("Create {0}", [child_type]), function () {
			frappe.new_doc("Task", {
				parent_task: frm.doc.name,
				custom_work_item_type: child_type,
				project: frm.doc.project,
			});
		});
	},

	custom_task_template: function (frm) {
		// Only populate an empty split table - don't clobber rows a PM has
		// already started filling in (or that already generated real Tasks)
		// just because the template link got re-saved. "Empty" means no row
		// has real content yet - a blank row from clicking "Add Row" still
		// counts as empty, not as something to preserve.
		const has_content_rows = (frm.doc.custom_task_split || []).some((row) => row.task_item);
		if (!frm.doc.custom_task_template || has_content_rows) {
			return;
		}

		frappe.call({
			method: "frappe.client.get",
			args: { doctype: "Task Template", name: frm.doc.custom_task_template },
			callback: function (r) {
				frm.clear_table("custom_task_split");
				(r.message.tasks || []).forEach(function (row) {
					const split_row = frm.add_child("custom_task_split");
					split_row.task_item = row.task_item;
					split_row.description = row.description;
				});
				frm.refresh_field("custom_task_split");
			},
		});
	},
});

// Task Split is a child table (istable=1) - it never renders as its own
// Desk form, so a .js file under its own doctype folder never loads. Child
// grid field events have to be registered from a script that DOES load, i.e.
// the parent's - this file already loads on every Task/Story form via the
// doctype_js hook, so registering the child doctype's events here works.
frappe.ui.form.on("Task Split", {
	create_action: function (frm, cdt, cdn) {
		if (frm.__task_split_perms && !frm.__task_split_perms.allocate_hours) {
			frappe.msgprint(__("Only a user with Allocate Hours access on this Project can create a Task from this row."));
			return;
		}

		const row = locals[cdt][cdn];
		if (!row.task_item) {
			frappe.msgprint(__("Fill in Task Item before creating a Task from this row."));
			return;
		}

		frappe.confirm(__("Create a Task for {0} without an Expected Hours budget?", [row.task_item]), function () {
			frappe.call({
				method: "sigzenjira.custom.task.create_task_without_hours",
				args: { row_name: row.name },
				freeze: true,
				callback: function () {
					frm.reload_doc();
				},
			});
		});
	},

	assign_action: function (frm, cdt, cdn) {
		if (frm.__task_split_perms && !frm.__task_split_perms.assign_users) {
			frappe.msgprint(__("You dont have permission to assign users from task-split "));
			return;
		}

		const row = locals[cdt][cdn];

		const dialog = new frappe.ui.Dialog({
			title: __("Assign"),
			fields: [
				{
					fieldname: "users",
					fieldtype: "MultiSelectPills",
					label: __("Users"),
					get_data: function (txt) {
						return frappe.db.get_link_options("User", txt);
					},
				},
			],
			primary_action_label: __("Update"),
			primary_action: function (values) {
				if (row.generated_task) {
					frappe.call({
						method: "sigzenjira.custom.task.set_split_row_assignees",
						args: { row_name: row.name, users: values.users },
						callback: function () {
							dialog.hide();
							frm.reload_doc();
						},
					});
				} else {
					// No Task yet - stage the picks on the row itself.
					// generate_tasks_from_split (custom/task.py) applies them as
					// real assignment the moment the Story save creates the Task.
					// The visible Assign column is otherwise only ever written by
					// the real-assignment sync (custom/todo.py), which has nothing
					// to sync yet - fill it in here too, purely so the pick shows
					// up immediately instead of looking like it did nothing.
					const users = values.users || [];
					frappe.model.set_value(cdt, cdn, "pending_assign_users", JSON.stringify(users));
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

		if (row.generated_task) {
			frappe.db.get_value("Task", row.generated_task, "_assign").then((r) => {
				const current = r.message._assign ? JSON.parse(r.message._assign) : [];
				dialog.set_value("users", current);
				dialog.show();
			});
		} else {
			const pending = row.pending_assign_users ? JSON.parse(row.pending_assign_users) : [];
			dialog.set_value("users", pending);
			dialog.show();
		}
	},
});
