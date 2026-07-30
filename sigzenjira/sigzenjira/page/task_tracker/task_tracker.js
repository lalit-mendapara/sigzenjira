// apps/sigzenjira/sigzenjira/sigzenjira/page/task_tracker/task_tracker.js
frappe.pages["task-tracker"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Task Tracker"),
		single_column: true,
	});

	wrapper.tracker_state = { project: null, employee: null };

	$(`<div class="task-tracker-layout">
		<div class="task-tracker-topbar" style="display:flex; align-items:center; gap:16px; flex-wrap:wrap; padding-bottom:12px; margin-bottom:12px; border-bottom:1px solid var(--border-color);"></div>
		<div class="task-tracker-main"></div>
	</div>`).appendTo(page.main);
};

frappe.pages["task-tracker"].refresh = (wrapper) => {
	// Task 3/4 wire real rendering here.
};
