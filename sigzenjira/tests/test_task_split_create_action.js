// Regression check for "Task Split row not found."
// Run: node sigzenjira/tests/test_task_split_create_action.js
//
// Loads task.js with stubbed Desk globals, grabs the Task Split create_action
// handler, and drives it through a FAILED save - frm.save() resolves even when
// the server throws (frappe/public/js/frappe/form/form.js after_save calls
// resolve() whether or not r.exc is set), so the row is still __islocal when
// the handler fires the server call, and create_task_from_split_row answers
// "Task Split row not found." on top of the real error.
//
// ponytail: plain node + vm, no jest - this app has no JS test runner and one
// file doesn't justify adding one.
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const SRC = path.join(__dirname, "..", "public", "js", "task.js");

const handlers = {};
const calls = [];
const messages = [];

const sandbox = {
	console,
	locals: {},
	document: { getElementById: () => null },
	$: () => ({ appendTo: () => {}, off: () => ({ on: () => {} }), on: () => {} }),
	cint: (v) => (v ? parseInt(v, 10) || 0 : 0),
	__: (s, args) => (args || []).reduce((t, a, i) => t.replace(`{${i}}`, a), s),
	frappe: {
		user_roles: ["Employee"],
		ui: {
			form: {
				on: (dt, h) => Object.assign((handlers[dt] = handlers[dt] || {}), h),
				// task.js patches this prototype at load time.
				AssignToDialog: { prototype: { get_fields: () => [] } },
			},
		},
		call: (opts) => calls.push(opts),
		msgprint: (m) => messages.push(m),
		confirm: (_msg, yes) => yes(),
		show_alert: () => {},
		model: { can_create: () => true, set_value: () => {} },
		db: {},
		new_doc: () => {},
	},
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(SRC, "utf8"), sandbox, { filename: SRC });

const create_action = handlers["Task Split"].create_action;

function run({ save_persists }) {
	calls.length = 0;
	messages.length = 0;
	const row = {
		doctype: "Task Split",
		name: "new-task-split-abc123",
		__islocal: 1,
		idx: 1,
		task_item: "Design",
	};
	sandbox.locals["Task Split"] = { row1: row };
	const frm = {
		doc: { custom_task_task_split: [row] },
		__task_split_perms: { allocate_hours: true, assign_users: true, set_work_item_type: true },
		is_new: () => false,
		is_dirty: () => true,
		reload_doc: () => {},
		save: () =>
			Promise.resolve().then(() => {
				if (save_persists) {
					delete row.__islocal;
					row.name = "abc123real";
				}
				// failed save: row stays __islocal, frm.save() still resolves
			}),
	};
	create_action(frm, "Task Split", "row1");
	return new Promise((r) => setImmediate(r));
}

(async () => {
	await run({ save_persists: true });
	assert.strictEqual(calls.length, 1, "happy path should call the server");
	assert.strictEqual(calls[0].args.row_name, "abc123real");

	await run({ save_persists: false });
	assert.strictEqual(
		calls.length,
		0,
		`failed save must NOT call create_task_from_split_row, got row_name=${
			calls[0] && calls[0].args.row_name
		}`
	);
	console.log("OK");
})();
