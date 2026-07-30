// apps/sigzenjira/sigzenjira/sigzenjira/page/task_tracker/task_tracker.js
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

const COLUMN_COLOR = {
	"To Do": "gray",
	"In Progress": "blue",
	"In Review": "orange",
	Done: "green",
};

frappe.pages["task-tracker"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Task Tracker"),
		single_column: true,
	});

	wrapper.tracker_state = {
		project: null,
		employee: null,
		ecd: frappe.datetime.get_today(),
	};
	wrapper.$projects = null;
	wrapper.$data = { projects: [], employees: [], epics: [] };

	wrapper.$layout = $(`<div class="task-tracker-layout">
		<div class="task-tracker-topbar">
			<select class="task-tracker-project-select form-control"></select>
			<select class="task-tracker-employee-select form-control" disabled></select>
			<input type="date" class="task-tracker-ecd-input form-control" value="${wrapper.tracker_state.ecd}">
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
		render_swimlanes(wrapper);
	});

	wrapper.$layout.find(".task-tracker-ecd-input").on("change", function () {
		wrapper.tracker_state.ecd = $(this).val() || null;
		render_swimlanes(wrapper);
	});
};

frappe.pages["task-tracker"].refresh = (wrapper) => {
	fetch_and_render(wrapper);
};

function fetch_and_render(wrapper) {
	if (!wrapper.tracker_state.project && wrapper.$projects !== null) {
		// Project list already known from an earlier load - no server round-trip
		// needed just to show the empty state.
		wrapper.$data = { projects: wrapper.$projects, employees: [], epics: [] };
		render_project_select(wrapper);
		render_employee_select(wrapper, []);
		render_swimlanes(wrapper);
		return;
	}

	frappe.call({
		method: "sigzenjira.sigzenjira.task_tracker.get_tracker_data",
		args: { project: wrapper.tracker_state.project },
		callback: (r) => {
			wrapper.$projects = r.message.projects;
			wrapper.$data = r.message;
			render_project_select(wrapper);
			render_employee_select(wrapper, r.message.employees);
			render_swimlanes(wrapper);
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

function status_badge_html(status) {
	const column = STATUS_COLUMN[status] || "To Do";
	const color = COLUMN_COLOR[column] || "gray";
	return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(status)}</span>`;
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
			<span class="task-tracker-avatars">${avatars}</span>
		</div>
	</div>`;
}

function render_columns(tasks, full_names) {
	const columns = {};
	BOARD_COLUMNS.forEach((c) => (columns[c] = []));
	tasks.forEach((t) => {
		const column = STATUS_COLUMN[t.status] || "To Do";
		columns[column].push(t);
	});

	const $row = $(`<div class="task-tracker-columns"></div>`);
	BOARD_COLUMNS.forEach((column_name) => {
		const cards = columns[column_name].map((t) => task_card_html(t, full_names)).join("");
		const $column = $(`<div class="task-tracker-column" data-column="${column_name}">
			<h6 class="task-tracker-column-header">
				<span>${__(column_name)}</span>
				<span class="task-tracker-column-count">${columns[column_name].length}</span>
			</h6>
			<div class="task-tracker-column-body">${cards}</div>
		</div>`);
		$row.append($column);
	});
	return $row;
}

function render_swimlanes(wrapper) {
	const $container = wrapper.$layout.find(".task-tracker-board").empty();

	if (!wrapper.tracker_state.project) {
		$container.append(
			`<div class="task-tracker-empty-state">${__("Select a project to view its board")}</div>`
		);
		return;
	}

	const epics = (wrapper.$data && wrapper.$data.epics) || [];
	const full_names = {};
	((wrapper.$data && wrapper.$data.employees) || []).forEach((e) => (full_names[e.name] = e.full_name));

	const { employee, ecd } = wrapper.tracker_state;
	const task_matches = (t) => {
		if (employee && !t.assignees.includes(employee)) return false;
		if (ecd && (!t.exp_end_date || t.exp_end_date.slice(0, 10) > ecd)) return false;
		return true;
	};

	let rendered_any = false;

	epics.forEach((epic) => {
		// Hidden entirely when structurally empty - the Epic never had any Task
		// descendants at all, not just none matching the current filters.
		const visible_stories = epic.stories.filter((s) => s.task_total > 0);
		if (!visible_stories.length) return;

		rendered_any = true;
		const epic_name_attr = epic.name ? ` data-name="${frappe.utils.escape_html(epic.name)}"` : "";
		const $epic = $(`<div class="task-tracker-epic">
			<div class="task-tracker-epic-header"${epic_name_attr}>
				<span class="task-tracker-epic-title">${frappe.utils.escape_html(epic.subject)}</span>
				${epic.name ? status_badge_html(epic.status) : ""}
			</div>
		</div>`);

		visible_stories.forEach((story) => {
			const matching_tasks = story.tasks.filter(task_matches);
			const story_name_attr = story.name ? ` data-name="${frappe.utils.escape_html(story.name)}"` : "";
			const $story = $(`<div class="task-tracker-story">
				<div class="task-tracker-story-header"${story_name_attr}>
					<span class="task-tracker-story-title">${frappe.utils.escape_html(story.subject)}</span>
					${story.name ? status_badge_html(story.status) : ""}
				</div>
			</div>`);

			if (!matching_tasks.length) {
				// Story has real Task descendants (task_total > 0 above) but none
				// survive the current Employee/ECD filter - stays visible so the
				// user knows this is a filter artifact, not a structural fact.
				$story.append(`<div class="task-tracker-no-match">${__("No matching tasks")}</div>`);
			} else {
				$story.append(render_columns(matching_tasks, full_names));
			}
			$epic.append($story);
		});

		$container.append($epic);
	});

	if (!rendered_any) {
		$container.append(`<div class="task-tracker-empty-state">${__("No tasks in this project yet")}</div>`);
	}

	$container.find(".task-tracker-card").on("click", function () {
		frappe.set_route("Form", "Task", $(this).attr("data-task"));
	});
	$container.find(".task-tracker-epic-header[data-name], .task-tracker-story-header[data-name]").on(
		"click",
		function () {
			frappe.set_route("Form", "Task", $(this).attr("data-name"));
		}
	);
}
