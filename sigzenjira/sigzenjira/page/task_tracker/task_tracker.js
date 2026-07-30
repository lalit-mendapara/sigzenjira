frappe.pages["task-tracker"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Task Tracker"),
		single_column: true,
	});

	wrapper.tracker_state = { project: null, employee: null };

	wrapper.$layout = $(`<div class="task-tracker-layout">
		<div class="task-tracker-topbar" style="display:flex; align-items:center; gap:16px; flex-wrap:wrap; padding-bottom:12px; margin-bottom:12px; border-bottom:1px solid var(--border-color);">
			<div class="task-tracker-projects" style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;"></div>
			<div class="task-tracker-divider" style="width:1px; align-self:stretch; background:var(--border-color);"></div>
			<div class="task-tracker-employees" style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;"></div>
		</div>
		<div class="task-tracker-main"></div>
	</div>`).appendTo(page.main);
};

frappe.pages["task-tracker"].refresh = (wrapper) => {
	fetch_and_render(wrapper);
};

function fetch_and_render(wrapper) {
	frappe.call({
		method: "sigzenjira.sigzenjira.task_tracker.get_tracker_data",
		args: {
			project: wrapper.tracker_state.project,
			employee: wrapper.tracker_state.employee,
		},
		callback: (r) => {
			render_topbar(wrapper, r.message);
			render_main(wrapper, r.message);
		},
	});
}

function render_topbar(wrapper, data) {
	const $projects = wrapper.$layout.find(".task-tracker-projects").empty();
	$projects.append(`<span class="text-muted small" style="margin-right:4px;">${__("Projects")}:</span>`);
	data.projects.forEach((project) => {
		const active = wrapper.tracker_state.project === project.name;
		const $pill = $(
			`<span class="task-tracker-item indicator-pill ${active ? "blue" : "gray"}" style="cursor:pointer;">${frappe.utils.escape_html(project.project_name)} (${project.task_count})</span>`
		);
		$pill.on("click", () => {
			wrapper.tracker_state.project = active ? null : project.name;
			fetch_and_render(wrapper);
		});
		$projects.append($pill);
	});

	const $employees = wrapper.$layout.find(".task-tracker-employees").empty();
	$employees.append(`<span class="text-muted small" style="margin-right:4px;">${__("Employees")}:</span>`);
	data.employees.forEach((employee) => {
		const active = wrapper.tracker_state.employee === employee.name;
		const $pill = $(
			`<span class="task-tracker-item indicator-pill ${active ? "blue" : "gray"}" style="cursor:pointer;">${frappe.utils.escape_html(employee.full_name)} (${employee.task_count})</span>`
		);
		$pill.on("click", () => {
			wrapper.tracker_state.employee = active ? null : employee.name;
			fetch_and_render(wrapper);
		});
		$employees.append($pill);
	});
}

const STATUS_COLORS = {
	Open: "gray",
	Working: "blue",
	"Pending Review": "orange",
	Overdue: "red",
	Blocked: "orange",
	Template: "gray",
	Completed: "green",
	Cancelled: "darkgrey",
};

function status_badge(status) {
	const color = STATUS_COLORS[status] || "gray";
	return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(status || "")}</span>`;
}

function task_row_html(task, show_project, project_names) {
	const project_cell = show_project
		? `<td>${frappe.utils.escape_html((project_names && project_names[task.project]) || task.project || "")}</td>`
		: "";
	return `<tr class="task-tracker-row" data-task="${frappe.utils.escape_html(task.name)}" style="cursor:pointer;">
		<td>${frappe.utils.escape_html(task.subject)}</td>
		<td>${frappe.utils.escape_html(task.work_item_type || "")}</td>
		<td>${status_badge(task.status)}</td>
		${project_cell}
	</tr>`;
}

function wire_row_clicks($container) {
	$container.find(".task-tracker-row").on("click", function () {
		frappe.set_route("Form", "Task", $(this).attr("data-task"));
	});
}

function render_main(wrapper, data) {
	const $main = wrapper.$layout.find(".task-tracker-main").empty();

	const project_names = {};
	data.projects.forEach((p) => (project_names[p.name] = p.project_name));

	if (wrapper.tracker_state.employee) {
		// Flat mode: single employee already picked, show Project column instead of grouping.
		const rows = data.tasks.map((t) => task_row_html(t, true, project_names)).join("");
		const $table = $(`<table class="table table-bordered">
			<thead><tr><th>${__("Task")}</th><th>${__("Type")}</th><th>${__("Status")}</th><th>${__("Project")}</th></tr></thead>
			<tbody>${rows || `<tr><td colspan="4" class="text-muted">${__("No tasks found")}</td></tr>`}</tbody>
		</table>`);
		$main.append($table);
		wire_row_clicks($table);
		return;
	}

	// Grouped mode: bucket the flat task list by assigned_to.
	const groups = {};
	const unassigned = [];
	data.tasks.forEach((t) => {
		if (!t.assigned_to) {
			unassigned.push(t);
			return;
		}
		groups[t.assigned_to] = groups[t.assigned_to] || [];
		groups[t.assigned_to].push(t);
	});

	const full_names = {};
	data.employees.forEach((e) => (full_names[e.name] = e.full_name));

	Object.keys(groups)
		.sort((a, b) => (full_names[a] || a).localeCompare(full_names[b] || b))
		.forEach((user) => {
			const rows = groups[user].map((t) => task_row_html(t, false)).join("");
			const $section = $(`<div style="margin-bottom:20px;">
				<h5>${frappe.utils.escape_html(full_names[user] || user)}</h5>
				<table class="table table-bordered">
					<thead><tr><th>${__("Task")}</th><th>${__("Type")}</th><th>${__("Status")}</th></tr></thead>
					<tbody>${rows}</tbody>
				</table>
			</div>`);
			$main.append($section);
			wire_row_clicks($section);
		});

	if (unassigned.length) {
		const rows = unassigned.map((t) => task_row_html(t, false)).join("");
		const $section = $(`<div style="margin-bottom:20px;">
			<h5 class="text-muted">${__("Unassigned")}</h5>
			<table class="table table-bordered">
				<thead><tr><th>${__("Task")}</th><th>${__("Type")}</th><th>${__("Status")}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`);
		$main.append($section);
		wire_row_clicks($section);
	}

	if (!Object.keys(groups).length && !unassigned.length) {
		$main.append(`<div class="text-muted">${__("No tasks found")}</div>`);
	}
}
