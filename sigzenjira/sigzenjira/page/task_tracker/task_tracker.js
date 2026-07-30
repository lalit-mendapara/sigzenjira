const STATUS_COLUMN = {
	Open: "To Do",
	Working: "In Progress",
	"Pending Review": "In Review",
	Completed: "Done",
	Cancelled: "Done",
	Overdue: "To Do",
	Blocked: "In Progress",
};

const BOARD_COLUMNS = ["To Do", "In Progress", "In Review", "Done"];

frappe.pages["task-tracker"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Task Tracker"),
		single_column: true,
	});

	wrapper.tracker_state = { project: null, employee: null };
	wrapper.$projects = null;

	wrapper.$layout = $(`<div class="task-tracker-layout">
		<div class="task-tracker-topbar">
			<select class="task-tracker-project-select form-control"></select>
			<select class="task-tracker-employee-select form-control" disabled></select>
		</div>
		<div class="task-tracker-board"></div>
	</div>`).appendTo(page.main);

	wrapper.$layout.find(".task-tracker-project-select").on("change", function () {
		wrapper.tracker_state.project = $(this).val() || null;
		wrapper.tracker_state.employee = null;
		fetch_and_render(wrapper);
	});

	wrapper.$layout.find(".task-tracker-employee-select").on("change", function () {
		wrapper.tracker_state.employee = $(this).val() || null;
		fetch_and_render(wrapper);
	});
};

frappe.pages["task-tracker"].refresh = (wrapper) => {
	fetch_and_render(wrapper);
};

function fetch_and_render(wrapper) {
	if (!wrapper.tracker_state.project && wrapper.$projects !== null) {
		// Project list already known from an earlier load — no server round-trip
		// needed just to show the empty state.
		render_project_select(wrapper);
		render_employee_select(wrapper, []);
		render_board(wrapper, [], []);
		return;
	}

	frappe.call({
		method: "sigzenjira.sigzenjira.task_tracker.get_tracker_data",
		args: {
			project: wrapper.tracker_state.project,
			employee: wrapper.tracker_state.employee,
		},
		callback: (r) => {
			wrapper.$projects = r.message.projects;
			render_project_select(wrapper);
			render_employee_select(wrapper, r.message.employees);
			render_board(wrapper, r.message.tasks, r.message.employees);
		},
	});
}

function render_project_select(wrapper) {
	const $select = wrapper.$layout.find(".task-tracker-project-select");
	const current = wrapper.tracker_state.project || "";
	const options = [`<option value="">${__("Select project")}</option>`]
		.concat(
			(wrapper.$projects || []).map(
				(p) =>
					`<option value="${frappe.utils.escape_html(p.name)}" ${p.name === current ? "selected" : ""}>${frappe.utils.escape_html(p.project_name)} (${p.task_count})</option>`
			)
		)
		.join("");
	$select.html(options);
}

function render_employee_select(wrapper, employees) {
	const $select = wrapper.$layout.find(".task-tracker-employee-select");
	const current = wrapper.tracker_state.employee || "";
	$select.prop("disabled", !wrapper.tracker_state.project);
	const options = [`<option value="">${__("All employees")}</option>`]
		.concat(
			(employees || []).map(
				(e) =>
					`<option value="${frappe.utils.escape_html(e.name)}" ${e.name === current ? "selected" : ""}>${frappe.utils.escape_html(e.full_name)} (${e.task_count})</option>`
			)
		)
		.join("");
	$select.html(options);
}

function get_initials(name) {
	return (name || "?")
		.split(" ")
		.filter(Boolean)
		.slice(0, 2)
		.map((part) => part[0].toUpperCase())
		.join("");
}

function task_card_html(task, full_names) {
	const avatars = task.assignees.length
		? task.assignees
				.map((a) => {
					const name = full_names[a] || a;
					return `<span class="task-tracker-avatar" title="${frappe.utils.escape_html(name)}">${frappe.utils.escape_html(get_initials(name))}</span>`;
				})
				.join("")
		: `<span class="task-tracker-avatar task-tracker-avatar-empty" title="${__("Unassigned")}">?</span>`;
	const overdue_flag =
		task.status === "Overdue" ? `<span class="indicator-pill red">${__("Overdue")}</span>` : "";
	const blocked_flag =
		task.status === "Blocked" ? `<span class="indicator-pill orange">${__("Blocked")}</span>` : "";
	const cancelled_flag =
		task.status === "Cancelled" ? `<span class="indicator-pill darkgrey">${__("Cancelled")}</span>` : "";
	return `<div class="task-tracker-card" data-task="${frappe.utils.escape_html(task.name)}">
		<div class="task-tracker-card-flags">${overdue_flag}${blocked_flag}${cancelled_flag}</div>
		<div class="task-tracker-card-title">${frappe.utils.escape_html(task.subject)}</div>
		<div class="task-tracker-card-footer">
			<span class="text-muted small">${frappe.utils.escape_html(task.work_item_type || "")}</span>
			<span class="task-tracker-avatars">${avatars}</span>
		</div>
	</div>`;
}

function render_board(wrapper, tasks, employees) {
	const $board = wrapper.$layout.find(".task-tracker-board").empty();

	if (!wrapper.tracker_state.project) {
		$board.append(
			`<div class="task-tracker-empty-state">${__("Select a project to view its board")}</div>`
		);
		return;
	}

	const full_names = {};
	(employees || []).forEach((e) => (full_names[e.name] = e.full_name));

	// One row per assignee comes in from the server; collapse back to one card
	// per task, listing all its assignees together.
	const deduped_tasks = {};
	tasks.forEach((t) => {
		if (!deduped_tasks[t.name]) {
			deduped_tasks[t.name] = { ...t, assignees: [] };
		}
		if (t.assigned_to) {
			deduped_tasks[t.name].assignees.push(t.assigned_to);
		}
	});

	const columns = {};
	BOARD_COLUMNS.forEach((c) => (columns[c] = []));
	Object.values(deduped_tasks).forEach((t) => {
		const column = STATUS_COLUMN[t.status] || "To Do";
		columns[column].push(t);
	});

	BOARD_COLUMNS.forEach((column_name) => {
		const cards = columns[column_name].map((t) => task_card_html(t, full_names)).join("");
		const $column = $(`<div class="task-tracker-column" data-column="${column_name}">
			<h6 class="task-tracker-column-header">
				<span>${__(column_name)}</span>
				<span class="task-tracker-column-count">${columns[column_name].length}</span>
			</h6>
			<div class="task-tracker-column-body">${cards}</div>
		</div>`);
		$board.append($column);
	});

	$board.find(".task-tracker-card").on("click", function () {
		frappe.set_route("Form", "Task", $(this).attr("data-task"));
	});
}
