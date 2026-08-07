// apps/sigzenjira/sigzenjira/sigzenjira/page/work_board/work_board.js
const API = "sigzenjira.sigzenjira.page.work_board.work_board";

// Completed and Cancelled Tasks never reach the board (see OPEN_STATUSES in
// work_board.py), so there is no Done column for them to land in.
const STATUS_COLUMN = {
	Open: "To Do",
	Overdue: "To Do",
	Working: "In Progress",
	Blocked: "In Progress",
	"Pending Review": "In Review",
};

const BOARD_COLUMNS = ["To Do", "In Progress", "In Review"];

const COLUMN_COLOR = {
	"To Do": "gray",
	"In Progress": "blue",
	"In Review": "orange",
};

// Statuses the column map folds into another column - kept visible as a flag on
// the card so nothing is silently lost in the grouping.
const STATUS_FLAG = {
	Overdue: "wb-flag-red",
	Blocked: "wb-flag-orange",
};

// Status "Overdue" is only stamped on by ERPNext's nightly Task.update_status,
// so a task that went past its ECD earlier today still reads as Open/Working -
// the date check is what makes the count match what the cards show.
const is_overdue = (task) =>
	task.status === "Overdue" ||
	(task.exp_end_date && task.exp_end_date < frappe.datetime.get_today());

// Nothing on the board carries a closed status any more (the server drops them
// from every row), so the fallback only ever covers a status the map misses.
const status_color = (status) => COLUMN_COLOR[STATUS_COLUMN[status]] || "green";

frappe.pages["work-board"].on_page_load = (wrapper) => {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Work Board"),
		single_column: true,
	});

	const board = new WorkBoard(page);
	wrapper.work_board = board;
	board.load();
};

// Coming back from a Task form (route change, not a reload) leaves the page
// instance - and its filter state - alive but its data stale. Refetch on show
// so edits made on the form appear without a browser refresh.
frappe.pages["work-board"].on_page_show = (wrapper) => {
	const board = wrapper.work_board;
	if (!board) return;
	// A deep link (the Work Board button on a Project) already fetches the board
	// it asked for; only a plain revisit needs the stale-data refetch.
	if (!board.apply_route_project()) board.refetch();
};

class WorkBoard {
	constructor(page) {
		this.page = page;
		this.state = {
			view: "project",
			project: null,
			department: null,
			// Current month by default - bounds the first load. Both bounds are
			// clearable; clearing them both means "no date limit". Only applies while
			// nothing is picked in the Epic/Story rows.
			from_date: frappe.datetime.month_start(),
			to_date: frappe.datetime.month_end(),
			employee_board_open: false,
			// The Epic and Story rows are multi-select: each holds the names picked
			// in it. Empty means "everything" rather than "nothing".
			epics: new Set(),
			stories: new Set(),
		};
		this.data = { tasks: [], members: [] };
		// Answered by get_bootstrap; false until it lands so a render that beats
		// the response never leaks the manager-only Employee Board.
		this.is_manager = false;
		// Per-user card layout, persisted server-side in __UserSettings through
		// save_card_fields - no settings doctype needed. Written via that API,
		// not frappe.model.user_settings.save, which only reaches redis.
		this.card_fields = [];
		this.render_shell();
	}

	card_fields_dialog() {
		// Options are fetched here rather than reused from page load, so the
		// dialog can never open against a not-yet-populated list.
		frappe.call(`${API}.get_card_field_options`).then((r) => {
			const options = r.message || [];
			if (!options.length) {
				frappe.msgprint(__("No Task fields are available to add to the card."));
				return;
			}
			const selected = new Set(this.card_fields);
			const dialog = new frappe.ui.Dialog({
				title: __("Card Fields"),
				fields: [
					{
						fieldname: "fields",
						fieldtype: "MultiCheck",
						label: __("Extra Task fields to show on every card"),
						columns: 2,
						select_all: true,
						options: options.map((opt) => ({
							label: opt.label,
							value: opt.fieldname,
							checked: selected.has(opt.fieldname),
						})),
					},
				],
				primary_action_label: __("Apply"),
				primary_action: () => {
					this.card_fields = dialog.get_value("fields") || [];
					frappe.call(`${API}.save_card_fields`, {
						fields: JSON.stringify(this.card_fields),
					});
					dialog.hide();
					this.refetch();
				},
			});
			dialog.show();
		});
	}

	// The chosen fields are fetched server-side, so a layout change needs the
	// current view's data again rather than a re-render of what's cached.
	refetch() {
		if (this.state.view === "project" && this.state.project) {
			this.fetch_project_board();
		} else if (this.state.view === "department" && this.state.department) {
			this.fetch_department_board();
		} else {
			this.render();
		}
	}

	render_shell() {
		this.$layout = $(`<div class="work-board">
			<div class="wb-toolbar">
				<div class="wb-controls wb-project-controls">
					<div class="wb-field">
						<label for="wb-project">${__("Project")}</label>
						<select id="wb-project" class="form-control wb-project"></select>
					</div>
					<div class="wb-field wb-range-field">
						<label for="wb-from-date">${__("Start Date")}</label>
						<input type="date" id="wb-from-date" class="form-control wb-from-date">
					</div>
					<div class="wb-field wb-range-field">
						<label for="wb-to-date">${__("ECD")}</label>
						<input type="date" id="wb-to-date" class="form-control wb-to-date">
					</div>
				</div>
				<div class="wb-controls wb-department-controls hidden">
					<div class="wb-field">
						<label for="wb-department">${__("Department")}</label>
						<select id="wb-department" class="form-control wb-department"></select>
					</div>
				</div>
				<div class="wb-field wb-view-field">
					<label for="wb-view">${__("View")}</label>
					<select id="wb-view" class="form-control wb-view">
						<option value="project">${__("Project View")}</option>
						<option value="department">${__("Department View")}</option>
					</select>
				</div>
				<button type="button" class="btn btn-default btn-sm wb-card-fields-btn">${__(
					"Card Fields"
				)}</button>
			</div>
			<div class="wb-body"></div>
		</div>`).appendTo(this.page.main);

		this.$body = this.$layout.find(".wb-body");
		this.$layout.find(".wb-from-date").val(this.state.from_date);
		this.$layout.find(".wb-to-date").val(this.state.to_date);
		this.bind_events();
	}

	bind_events() {
		// Lives in the board's own toolbar rather than the page ⋮ menu - the
		// header menu renders empty for this page.
		this.$layout.on("click", ".wb-card-fields-btn", () => this.card_fields_dialog());

		this.$layout.on("change", ".wb-view", (e) => {
			const view = e.target.value;
			if (view === this.state.view) return;
			this.state.view = view;
			this.$layout.find(".wb-project-controls").toggleClass("hidden", view !== "project");
			this.$layout
				.find(".wb-department-controls")
				.toggleClass("hidden", view !== "department");
			// Both views share this.data - rendering straight away would draw the
			// new view over the other one's tasks.
			this.data = { tasks: [], members: [] };
			this.refetch();
		});

		this.$layout.on("change", ".wb-project", (e) => {
			this.state.project = e.target.value || null;
			// Every selection belongs to the old project - carrying one over would
			// filter the new board by names that are not on it.
			this.clear_selection();
			this.data = { tasks: [], members: [] };
			// Nothing picked in the rows yet, so the board opens on the project's
			// Tasks due inside the toolbar's range.
			if (this.state.project) {
				this.fetch_project_board();
			} else {
				this.render();
			}
		});

		this.$layout.on("change", ".wb-from-date, .wb-to-date", (e) => {
			const key = e.target.classList.contains("wb-from-date") ? "from_date" : "to_date";
			this.state[key] = e.target.value || null;
			this.refetch();
		});

		this.$layout.on("change", ".wb-department", (e) => {
			this.state.department = e.target.value || null;
			if (this.state.department) {
				this.fetch_department_board();
			} else {
				this.data = { tasks: [], members: [] };
				this.render();
			}
		});

		// Multi-select. Picking in the Epic row narrows the Story row, and the Story
		// row narrows the kanban - so an Epic click has to drop any Story picked
		// under an Epic that is no longer selected, or the kanban would keep showing
		// work from an Epic the user just cleared.
		this.$layout.on("click", ".wb-chip", (e) => {
			const $chip = $(e.currentTarget);
			const set = this.state[$chip.data("row")];
			const name = $chip.data("name");
			if (set.has(name)) set.delete(name);
			else set.add(name);
			if ($chip.data("row") === "epics") this.prune_stories();
			// The selection is what the server filters the cards by, so this is a
			// refetch and not just a redraw.
			this.fetch_project_board();
		});

		// Inside a chip, whose own click toggles the selection - this one routes to
		// the work item's form instead.
		this.$layout.on("click", ".wb-chip-id", (e) => {
			e.stopPropagation();
			frappe.set_route("Form", "Task", $(e.currentTarget).closest(".wb-chip").data("name"));
		});

		// Sits inside the chip, so .wb-chip-id's closest(".wb-chip") would resolve
		// to the Story instead of the step's own Task - hence its own class and a
		// data-task of its own, and stopPropagation for the chip's toggle.
		this.$layout.on("click", ".wb-step-id", (e) => {
			e.stopPropagation();
			frappe.set_route("Form", "Task", $(e.currentTarget).data("task"));
		});

		this.$layout.on("click", ".wb-clear-row", (e) => {
			this.state[$(e.currentTarget).data("row")].clear();
			if ($(e.currentTarget).data("row") === "epics") this.prune_stories();
			this.fetch_project_board();
		});

		// `toggle` doesn't bubble, so it is captured rather than delegated.
		this.$layout.get(0).addEventListener(
			"toggle",
			(e) => {
				if (e.target.classList.contains("wb-employee-section")) {
					this.state.employee_board_open = e.target.open;
				}
			},
			true
		);

		// Routes to the Issue a Story was raised from, not to the Story - so it has
		// to stop the chip's own toggle handler.
		this.$layout.on("click", ".wb-issue-link", (e) => {
			e.stopPropagation();
			frappe.set_route("Form", "Issue", $(e.currentTarget).data("issue"));
		});

		this.$layout.on("click", ".wb-card", (e) => {
			frappe.set_route("Form", "Task", $(e.currentTarget).data("name"));
		});
	}

	clear_selection() {
		this.state.epics.clear();
		this.state.stories.clear();
	}

	// Stories picked under an Epic that is no longer selected. Kept as a set
	// operation rather than clearing the row outright: narrowing the Epic row
	// should leave the picks that are still reachable alone.
	prune_stories() {
		if (!this.state.epics.size) return;
		const visible = new Set(this.visible_stories().map((story) => story.name));
		this.state.stories.forEach((name) => {
			if (!visible.has(name)) this.state.stories.delete(name);
		});
	}

	// The Story row's contents: every open Story, or only those under the picked
	// Epics.
	visible_stories() {
		const stories = this.data.stories || [];
		if (!this.state.epics.size) return stories;
		return stories.filter((story) => this.state.epics.has(story.epic));
	}

	// What the server filters the cards by. null = nothing picked anywhere, so the
	// whole project (inside the date range) is the answer. An empty array is a real
	// answer too: picked Epics that hold no open Story at all.
	selected_stories() {
		if (this.state.stories.size) return [...this.state.stories];
		if (!this.state.epics.size) return null;
		return this.visible_stories().map((story) => story.name);
	}

	// Deep link support: frappe.route_options.project preselects the picker.
	// Fires the picker's own change handler rather than duplicating it. Left
	// untouched when the option is missing - on the first visit that just means
	// get_bootstrap hasn't answered yet, and load() retries once it has (a
	// project the user can't see is never in the list, so it stays unapplied).
	apply_route_project() {
		const project = frappe.route_options && frappe.route_options.project;
		if (!project) return false;
		const $project = this.$layout.find(".wb-project");
		if (!$project.find("option").filter((i, o) => o.value === project).length) return false;
		delete frappe.route_options.project;
		$project.val(project).trigger("change");
		return true;
	}

	load() {
		// Task meta is needed to format the user-chosen extra fields on the card
		// (frappe.format needs the docfield, not just the raw value).
		frappe.model.with_doctype("Task");
		frappe.model.user_settings.get("Task").then((settings) => {
			this.card_fields = settings.work_board_card_fields || [];
			if (this.card_fields.length) this.refetch();
		});

		frappe.call(`${API}.get_bootstrap`).then((r) => {
			const data = r.message || { projects: [], departments: [] };
			this.is_manager = !!data.is_manager;

			const $project = this.$layout.find(".wb-project");
			$project.append(`<option value="">${__("Select Project")}</option>`);
			data.projects.forEach((p) => {
				$project.append(
					`<option value="${frappe.utils.escape_html(
						p.name
					)}">${frappe.utils.escape_html(p.project_name || p.name)}</option>`
				);
			});

			const $department = this.$layout.find(".wb-department");
			$department.append(`<option value="">${__("Select Department")}</option>`);
			data.departments.forEach((d) => {
				$department.append(
					`<option value="${frappe.utils.escape_html(d)}">${frappe.utils.escape_html(
						d
					)}</option>`
				);
			});
			// get_bootstrap already refuses the department data to non-managers;
			// this drops the control that would otherwise sit there empty.
			if (!data.is_manager) {
				this.$layout.find('.wb-view option[value="department"]').remove();
				this.$layout.find(".wb-department-controls").remove();
				this.$layout.find(".wb-view-field").addClass("hidden");
			}

			// The picker is populated now, so a deep link that on_page_show was
			// too early to honour lands here. Applying it fetches its own board.
			if (!this.apply_route_project()) this.render();
		});
	}

	fetch_project_board() {
		const stories = this.selected_stories();
		// The range only bounds an unfiltered board, so it is greyed out once
		// something is picked rather than left looking live.
		this.$layout.find(".wb-from-date, .wb-to-date").prop("disabled", stories !== null);
		frappe
			.call(`${API}.get_project_board`, {
				project: this.state.project,
				stories: stories === null ? "" : JSON.stringify(stories),
				from_date: this.state.from_date,
				to_date: this.state.to_date,
				extra_fields: JSON.stringify(this.card_fields),
			})
			.then((r) => {
				this.data = r.message || { tasks: [], members: [] };
				this.render();
			});
	}

	fetch_department_board() {
		frappe
			.call(`${API}.get_department_board`, {
				department: this.state.department,
				extra_fields: JSON.stringify(this.card_fields),
			})
			.then((r) => {
				this.data = r.message || { tasks: [], members: [] };
				this.render();
			});
	}

	render() {
		if (this.state.view === "project") {
			this.render_project_view();
		} else {
			this.render_department_view();
		}
	}

	// Three rows, top to bottom: Epics, Stories, then the Task kanban. Each row
	// filters the one below it, so what is on screen is always readable straight
	// down - no drilling in and no collapsed sections hiding the work.
	render_project_view() {
		if (!this.state.project) {
			this.$body.html(this.empty_state(__("Select a Project to begin.")));
			return;
		}
		const tasks = this.data.tasks || [];
		const epics = this.data.epics || [];
		const stories = this.visible_stories();

		// Who-is-working-on-what across the whole team is a manager question;
		// a project member gets the kanban only.
		const employee_board = this.is_manager
			? this.section(
					__("Employee Board"),
					tasks.length,
					this.employee_columns(tasks, this.data.members || [], false),
					// Collapsed until asked for - the kanban answers the first
					// question. State survives re-renders via the toggle handler.
					{ open: this.state.employee_board_open, cls: "wb-employee-section" }
			  )
			: "";

		this.$body.html(`
			${this.chip_row(__("Epics"), "epics", epics)}
			${this.chip_row(__("Stories"), "stories", stories)}
			${this.section(__("Tasks"), tasks.length, this.status_columns(tasks), {
				columns_cls: "wb-columns-fill",
			})}
			${employee_board}
		`);
		this.setup_sortable();
	}

	// Re-created on every render: $body.html() throws the old lists away, and
	// Sortable's instance lives on the element it was given.
	setup_sortable() {
		// The status kanban only. An employee column means "who is this on",
		// so a drop there is a reassignment, not a status change - wiring it to
		// the same handler would silently set the wrong field.
		if (!frappe.model.can_write("Task")) return;
		this.$body.find(".wb-columns-fill .wb-cards").each((i, el) => {
			Sortable.create(el, {
				group: "wb-tasks",
				animation: 150,
				// Without this the "No tasks" placeholder is draggable too, and
				// an empty column still has to accept a drop.
				draggable: ".wb-card",
				onEnd: (e) => this.on_card_drop(e),
			});
		});
	}

	on_card_drop(e) {
		const $to = $(e.to).closest(".wb-column");
		const column = $to.data("column");
		// Same column: the board has no manual card order to persist, so a
		// reorder is a no-op rather than a write that changes nothing.
		if (!column || column === $(e.from).closest(".wb-column").data("column")) return;
		const name = $(e.item).data("name");
		frappe.call({
			method: `${API}.set_task_status`,
			args: { task: name, column },
			freeze: true,
			freeze_message: __("Moving {0}", [name]),
			// Refetch either way. On success the server has moved more than the
			// one card (Story/Epic rollups, the stat tiles); on failure the drop
			// has already moved the node and a re-render is what puts it back.
			callback: () => this.refetch(),
			error: () => this.refetch(),
		});
	}

	// One selectable row. `row` is the state key it drives, which is also what the
	// click handler reads off the chip - so the two rows share every line of this.
	chip_row(label, row, items) {
		const picked = this.state[row];
		const chips = items.length
			? items.map((item) => this.chip(row, item, picked.has(item.name))).join("")
			: `<div class="wb-row-empty">${
					row === "stories" && this.state.epics.size
						? __("No open stories under the selected epics")
						: __("Nothing open here")
			  }</div>`;
		// Only offered once something is picked - an always-on Clear reads as if
		// something were filtered when nothing is.
		const clear = picked.size
			? `<span class="wb-clear-row" data-row="${row}">${__("Clear")}</span>`
			: "";
		return `<div class="wb-row">
			<div class="wb-row-head">
				<span class="wb-row-label">${frappe.utils.escape_html(label)}</span>
				<span class="wb-count">${items.length}</span>
				${picked.size ? `<span class="wb-row-picked">${__("{0} selected", [picked.size])}</span>` : ""}
				${clear}
			</div>
			<div class="wb-chips">${chips}</div>
		</div>`;
	}

	chip(row, item, selected) {
		const color = status_color(item.status);
		// Stories raised from an Issue (events/issue.py) link back to it - its own
		// class, so the click routes to Issue and not to the Task the chip is for.
		const issue = item.issue
			? `<span class="wb-issue-link" data-issue="${frappe.utils.escape_html(item.issue)}"
					title="${__("Open Issue")}">${frappe.utils.escape_html(item.issue)}</span>`
			: "";
		// Only the picked chip answers "where is this Story right now" - on every
		// chip it would be a second status column nobody asked for.
		const step = selected ? this.chip_step(item.current_step) : "";
		return `<div class="wb-chip wb-chip-${color} ${selected ? "selected" : ""} ${step ? "has-step" : ""}"
				data-row="${row}" data-name="${frappe.utils.escape_html(item.name)}">
			<div class="wb-chip-head">
				<span class="wb-dot wb-dot-${color}"></span>
				<span class="wb-chip-subject" title="${frappe.utils.escape_html(
					item.subject || item.name
				)}">${frappe.utils.escape_html(item.subject || item.name)}</span>
				<span class="wb-pill wb-pill-${color}">${__(item.status)}</span>
				<span class="wb-chip-id" title="${__("Open")}">${frappe.utils.escape_html(item.name)}</span>
				${issue}
			</div>
			${step}
		</div>`;
	}

	// The Story's current step: the first split row in sequence that generated a
	// Task still open (work_board.py:_current_steps). Absent until a Task exists,
	// and gone again once every generated row is closed - the line is about work
	// in flight, not work planned.
	chip_step(step) {
		if (!step) return "";
		const color = status_color(step.status);
		// Full names, comma-joined - a step Task usually has one assignee, and the
		// several-assignee case is rare enough not to earn avatars here.
		const who = (step.assignees || []).join(", ");
		const assignees = who
			? `<span class="wb-step-who" title="${frappe.utils.escape_html(who)}">${frappe.utils.escape_html(
					who
			  )}</span>`
			: "";
		return `<div class="wb-chip-step">
			<span class="wb-step-seq">${step.idx}.</span>
			<span class="wb-step-item" title="${frappe.utils.escape_html(step.task_item || "")}">${frappe.utils.escape_html(
			step.task_item || ""
		)}</span>
			<span class="wb-pill wb-pill-${color}">${__(step.status)}</span>
			${assignees}
			<span class="wb-step-id" data-task="${frappe.utils.escape_html(step.task)}"
				title="${__("Open")}">${frappe.utils.escape_html(step.task)}</span>
		</div>`;
	}

	render_department_view() {
		if (!this.state.department) {
			this.$body.html(this.empty_state(__("Select a Department to begin.")));
			return;
		}
		const tasks = this.data.tasks || [];
		this.$body.html(
			this.section(
				__("Open Work by Employee"),
				tasks.length,
				this.employee_columns(tasks, this.data.members || [], true)
			)
		);
	}

	empty_state(message) {
		return `<div class="wb-empty">${frappe.utils.escape_html(message)}</div>`;
	}

	// columns_cls: the Task kanban has a fixed set of columns, so they share the
	// full width. The employee board has one per member and stays scrollable.
	section(title, count, columns_html, { open = true, cls = "", columns_cls = "" } = {}) {
		return `<details class="wb-section ${cls}" ${open ? "open" : ""}>
			<summary class="wb-section-title">${frappe.utils.escape_html(title)}
				<span class="wb-count">${count}</span></summary>
			<div class="wb-columns ${columns_cls}">${columns_html}</div>
		</details>`;
	}

	status_columns(tasks) {
		const buckets = {};
		BOARD_COLUMNS.forEach((c) => (buckets[c] = []));
		tasks.forEach((task) => {
			const column = STATUS_COLUMN[task.status] || "To Do";
			buckets[column].push(task);
		});
		return BOARD_COLUMNS.map((column) =>
			this.column(column, buckets[column], COLUMN_COLOR[column], false)
		).join("");
	}

	employee_columns(tasks, members, show_project) {
		const buckets = {};
		members.forEach((m) => (buckets[m.user] = []));

		// Unassigned tasks are deliberately dropped here - this board answers
		// "what is on each person's plate". They still show on the status board.
		tasks.forEach((task) => {
			// A task with N assignees is a card in each of their columns.
			task.assignees.forEach((a) => {
				if (buckets[a.user]) buckets[a.user].push(task);
			});
		});

		const columns = members.map((m) =>
			this.column(m.full_name, buckets[m.user], "gray", show_project, m)
		);
		if (!columns.length) {
			return `<div class="wb-empty">${__("No employees found.")}</div>`;
		}
		return columns.join("");
	}

	column(title, tasks, color, show_project, member) {
		tasks = tasks || [];
		const avatar = member ? this.avatar(member) : "";
		// No member means this came from status_columns(), where `title` is the
		// raw BOARD_COLUMNS key (the heading is rendered untranslated) - which
		// is exactly what set_task_status wants back. Employee columns get no
		// data-column, so a stray drop there resolves to undefined and is
		// dropped by on_card_drop rather than writing a status.
		const column_attr = member ? "" : ` data-column="${frappe.utils.escape_html(title)}"`;
		const cards = tasks.length
			? tasks.map((t) => this.card(t, show_project, !!member)).join("")
			: `<div class="wb-column-empty">${__("No tasks")}</div>`;
		return `<div class="wb-column wb-column-${color}"${column_attr}>
			<div class="wb-column-head">
				<span class="wb-dot wb-dot-${color}"></span>
				${avatar}
				<span class="wb-column-title">${frappe.utils.escape_html(title)}</span>
				<span class="wb-count">${tasks.length}</span>
			</div>
			<div class="wb-cards">${cards}</div>
		</div>`;
	}

	avatar(member) {
		// css_class must stay exactly "avatar-xs" - frappe.get_avatar compares it
		// literally to decide the 1-letter abbreviation.
		return frappe.avatar(member.user, "avatar-xs", member.full_name, member.user_image);
	}

	// User-chosen Task fields, formatted through the docfield so Dates, Links,
	// Currency and Check render the way they do everywhere else in Desk.
	extra_lines(task) {
		const fields = this.data.extra_fields || [];
		if (!fields.length || !task.extra) return "";
		const meta = frappe.get_meta("Task");
		return fields
			.map((fieldname) => {
				const value = task.extra[fieldname];
				if (value === null || value === undefined || value === "") return "";
				const df = meta && meta.fields.find((f) => f.fieldname === fieldname);
				const formatted = df
					? frappe.format(value, df, { only_value: 1 }, task)
					: frappe.utils.escape_html(String(value));
				return `<div class="wb-card-extra">
					<span class="wb-extra-label">${frappe.utils.escape_html(
						df ? __(df.label || fieldname) : fieldname
					)}</span>
					<span class="wb-extra-value">${formatted}</span>
				</div>`;
			})
			.join("");
	}

	card(task, show_project, show_status) {
		const overdue = is_overdue(task);
		const flag = STATUS_FLAG[task.status]
			? `<span class="wb-flag ${STATUS_FLAG[task.status]}">${__(task.status)}</span>`
			: "";
		const status_pill = show_status
			? `<span class="wb-pill wb-pill-${status_color(task.status)}">${__(
					STATUS_COLUMN[task.status] || task.status
			  )}</span>`
			: "";
		const project = show_project
			? `<div class="wb-card-project">${frappe.utils.escape_html(
					task.project_name || task.project || ""
			  )}</div>`
			: "";
		const ecd = task.exp_end_date
			? `<span class="wb-ecd ${overdue ? "wb-ecd-late" : ""}">${frappe.datetime.str_to_user(
					task.exp_end_date
			  )}</span>`
			: "";
		const avatars = task.assignees.map((a) => this.avatar(a)).join("");

		return `<div class="wb-card" data-name="${frappe.utils.escape_html(task.name)}">
			<div class="wb-card-head">
				<span class="wb-card-id">${frappe.utils.escape_html(task.name)}</span>
				${flag}${status_pill}
			</div>
			<div class="wb-card-subject">${frappe.utils.escape_html(task.subject || "")}</div>
			${project}
			${this.extra_lines(task)}
			<div class="wb-card-foot">
				<span class="wb-avatars">${avatars}</span>
				${ecd}
			</div>
		</div>`;
	}
}
