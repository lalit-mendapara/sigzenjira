const STATUS_COLUMN = {
	Open: "To Do",
	Template: "To Do",
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
		<div class="task-tracker-topbar" style="display:flex; align-items:center; gap:16px; flex-wrap:wrap; padding-bottom:12px; margin-bottom:12px; border-bottom:1px solid var(--border-color);">
			<select class="task-tracker-project-select form-control" style="width:220px;"></select>
			<select class="task-tracker-employee-select form-control" style="width:220px;" disabled></select>
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

function task_card_html(task, full_names) {
	const assignee = task.assignees.length
		? task.assignees.map((a) => frappe.utils.escape_html(full_names[a] || a)).join(", ")
		: __("Unassigned");
	const overdue_flag =
		task.status === "Overdue"
			? `<span class="indicator-pill red" style="margin-bottom:4px;">${__("Overdue")}</span>`
			: "";
	const blocked_flag =
		task.status === "Blocked"
			? `<span class="indicator-pill orange" style="margin-bottom:4px;">${__("Blocked")}</span>`
			: "";
	return `<div class="task-tracker-card" data-task="${frappe.utils.escape_html(task.name)}" style="cursor:pointer; border:1px solid var(--border-color); border-radius:6px; padding:8px; margin-bottom:8px;">
		${overdue_flag}
		${blocked_flag}
		<div>${frappe.utils.escape_html(task.subject)}</div>
		<div class="text-muted small">${frappe.utils.escape_html(task.work_item_type || "")}</div>
		<div class="text-muted small">${assignee}</div>
	</div>`;
}

function render_board(wrapper, tasks, employees) {
	const $board = wrapper.$layout.find(".task-tracker-board").empty();

	if (!wrapper.tracker_state.project) {
		$board.css({ display: "block" });
		$board.append(`<div class="text-muted">${__("Select a project to view its board")}</div>`);
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

	$board.css({ display: "flex", gap: "16px", "align-items": "flex-start" });
	BOARD_COLUMNS.forEach((column_name) => {
		const cards = columns[column_name].map((t) => task_card_html(t, full_names)).join("");
		const $column = $(`<div class="task-tracker-column" style="flex:1; min-width:220px;">
			<h6>${__(column_name)} (${columns[column_name].length})</h6>
			<div class="task-tracker-column-body">${cards}</div>
		</div>`);
		$board.append($column);
	});

	$board.find(".task-tracker-card").on("click", function () {
		frappe.set_route("Form", "Task", $(this).attr("data-task"));
	});
}
