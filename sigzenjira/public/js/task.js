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

frappe.ui.form.on("Task", {
	onload: function (frm) {
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

		frm.fields_dict.custom_task_split.grid.cannot_add_rows =
			!WORK_ITEM_TYPE_PRIVILEGED_ROLES.some((role) => frappe.user_roles.includes(role));
		frm.fields_dict.custom_task_split.grid.refresh();

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
