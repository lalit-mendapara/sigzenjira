frappe.pages["task-tracker"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Task Tracker"),
		single_column: true,
	});

	wrapper.tracker_state = { project: null, employee: null };

	$(`<div class="task-tracker-layout">
		<div class="task-tracker-topbar" style="display:flex; align-items:center; gap:16px; flex-wrap:wrap; padding-bottom:12px; margin-bottom:12px; border-bottom:1px solid var(--border-color);">
			<div class="task-tracker-projects" style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;"></div>
			<div class="task-tracker-divider" style="width:1px; align-self:stretch; background:var(--border-color);"></div>
			<div class="task-tracker-employees" style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;"></div>
		</div>
		<div class="task-tracker-main"></div>
	</div>`).appendTo(page.main);

	fetch_and_render(wrapper);
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
	const $projects = wrapper.find(".task-tracker-projects").empty();
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

	const $employees = wrapper.find(".task-tracker-employees").empty();
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

function render_main(wrapper, data) {
	// Stub — Task 4 replaces this with grouped/flat rendering.
	wrapper.find(".task-tracker-main").html(`<pre>${frappe.utils.escape_html(JSON.stringify(data.tasks, null, 2))}</pre>`);
}
