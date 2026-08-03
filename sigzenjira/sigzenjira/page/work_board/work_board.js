// apps/sigzenjira/sigzenjira/sigzenjira/page/work_board/work_board.js
const API = "sigzenjira.sigzenjira.work_board";

// The four counters over the board: Epic/Story x Open/Working.
const STAT_TILES = [
	{ type: "Epic", status: "Open", color: "gray" },
	{ type: "Epic", status: "Working", color: "blue" },
	{ type: "Story", status: "Open", color: "gray" },
	{ type: "Story", status: "Working", color: "blue" },
];

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

// Cards only ever carry an open status, but the context strip shows the picked
// item's Epic/Story ancestors, and those can be Completed or Cancelled.
const status_color = (status) =>
	COLUMN_COLOR[STATUS_COLUMN[status]] || (status === "Cancelled" ? "gray" : "green");

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
			item: null,
			item_label: "",
			department: null,
			// Current month by default - bounds the first load. Both bounds are
			// clearable; clearing them both means "no date limit".
			from_date: frappe.datetime.month_start(),
			to_date: frappe.datetime.month_end(),
			employee_board_open: false,
			// Active stat tile, e.g. {type: "Story", status: "Working"}.
			stat_type: null,
			stat_status: null,
			// Overdue tile - a client-side filter on the loaded board, not a
			// server one, so it stacks on top of whatever else is picked.
			overdue_only: false,
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
					<div class="wb-field wb-search-field">
						<label for="wb-item">${__("Work Item")}</label>
						<input type="text" id="wb-item" class="form-control wb-item" autocomplete="off"
							placeholder="${__("None - all tasks in the project")}" disabled>
						<div class="wb-search-results"></div>
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
			this.hide_results();
			// Both views share this.data - rendering straight away would draw the
			// new view over the other one's tasks (and without its stats).
			this.data = { tasks: [], members: [] };
			this.refetch();
		});

		this.$layout.on("change", ".wb-project", (e) => {
			this.state.project = e.target.value || null;
			// Counts belong to the old project - carrying the tile over would
			// filter the new board by a selection the user never made on it.
			this.state.stat_type = null;
			this.state.stat_status = null;
			this.state.overdue_only = false;
			this.clear_item();
			this.$layout.find(".wb-item").prop("disabled", !this.state.project);
			// No work item yet - the server answers with the project's tasks due
			// today, so the board is useful straight after picking a Project.
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

		const search = frappe.utils.debounce(() => this.search_items(), 300);
		this.$layout.on("input", ".wb-item", search);
		this.$layout.on("focus", ".wb-item", () => this.search_items());

		this.$layout.on("click", ".wb-search-result", (e) => {
			const $row = $(e.currentTarget);
			if (!$row.data("name")) {
				this.clear_item();
				this.fetch_project_board();
				return;
			}
			this.state.item = $row.data("name");
			this.state.item_label = $row.data("label");
			this.$layout.find(".wb-item").val(`${this.state.item}: ${this.state.item_label}`);
			// A work item's board is never date-limited, so the range is greyed out
			// rather than left looking live.
			this.$layout.find(".wb-from-date, .wb-to-date").prop("disabled", true);
			this.hide_results();
			this.fetch_project_board();
		});

		$(document).on("click.work_board", (e) => {
			if (!$(e.target).closest(".wb-search-field").length) this.hide_results();
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

		// Inside a <summary>, so the default action would collapse the lane as well as
		// route away. The .wb-card handler below still fires and does the routing.
		this.$layout.on("click", ".wb-lane-link", (e) => e.preventDefault());

		// Same, but this one routes itself - it is not a .wb-card, and it sits
		// inside the lane header, so the toggle has to be stopped here too.
		this.$layout.on("click", ".wb-issue-link", (e) => {
			e.preventDefault();
			frappe.set_route("Form", "Issue", $(e.currentTarget).data("issue"));
		});

		this.$layout.on("click", ".wb-stat", (e) => {
			const $tile = $(e.currentTarget);
			if ($tile.hasClass("inert")) return;
			const type = $tile.data("type");
			const status = $tile.data("status");
			// Overdue filters the tasks already loaded - no server round trip,
			// and the cards stay in the status column they belong to.
			if (type === "Overdue") {
				this.state.overdue_only = !this.state.overdue_only;
				this.render();
				return;
			}
			// Clicking the active tile clears it - the tiles are a single-choice
			// filter, so there is no separate "clear" control to miss.
			const same = this.state.stat_type === type && this.state.stat_status === status;
			this.state.stat_type = same ? null : type;
			this.state.stat_status = same ? null : status;
			this.refetch();
		});

		this.$layout.on("click", ".wb-card", (e) => {
			frappe.set_route("Form", "Task", $(e.currentTarget).data("name"));
		});
	}

	clear_item() {
		this.state.item = null;
		this.state.item_label = "";
		this.$layout.find(".wb-item").val("");
		this.$layout.find(".wb-from-date, .wb-to-date").prop("disabled", false);
		this.hide_results();
		this.data = { tasks: [], members: [] };
	}

	hide_results() {
		this.$layout.find(".wb-search-results").empty().removeClass("open");
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

	search_items() {
		if (!this.state.project) return;
		frappe
			.call(`${API}.search_work_items`, {
				project: this.state.project,
				txt: this.$layout.find(".wb-item").val(),
			})
			.then((r) => {
				const rows = r.message || [];
				const $results = this.$layout.find(".wb-search-results").empty();
				// The only way back to the project-wide board - the picker is a
				// free-text box with no other clear affordance.
				$results.append(
					$(`<div class="wb-search-result">
						<span class="wb-search-type">${__("None")}</span>
						<span class="wb-search-subject">${__("All tasks in the project")}</span>
					</div>`).data({ name: "", label: "" })
				);
				if (!rows.length) {
					$results
						.addClass("open")
						.append(`<div class="wb-search-empty">${__("No work items found")}</div>`);
					return;
				}
				rows.forEach((row) => {
					$results.append(
						$(`<div class="wb-search-result">
							<span class="wb-search-type">${__(row.work_item_type)}</span>
							<span class="wb-search-id">${frappe.utils.escape_html(row.name)}</span>
							<span class="wb-search-subject">${frappe.utils.escape_html(row.subject || "")}</span>
						</div>`).data({ name: row.name, label: row.subject || "" })
					);
				});
				$results.addClass("open");
			});
	}

	fetch_project_board() {
		frappe
			.call(`${API}.get_project_board`, {
				project: this.state.project,
				item: this.state.item,
				from_date: this.state.from_date,
				to_date: this.state.to_date,
				extra_fields: JSON.stringify(this.card_fields),
				stat_type: this.state.stat_type,
				stat_status: this.state.stat_status,
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

	render_project_view() {
		if (!this.state.project) {
			this.$body.html(this.empty_state(__("Select a Project to begin.")));
			return;
		}
		const all_tasks = this.data.tasks || [];
		const tasks = this.state.overdue_only ? all_tasks.filter(is_overdue) : all_tasks;
		const stories = this.data.stories || [];
		const filter_on = !!this.state.stat_type || this.state.overdue_only;
		// An item board is already scoped to what was picked; the project-wide board
		// is the one that has to name what a tile filtered it down to.
		const item_board = !!this.state.item;
		const epics = this.data.epics || [];
		// Sections on the picked item's own chain open on arrival - the rest of the
		// board stays collapsed. Empty on a tile-filtered board, which opens nothing.
		const path = new Set(this.data.path || []);
		// An Epic's board splits into one lane per Story. A project-wide board pools
		// its cards - until a tile is on, when it splits the same way: the tile
		// counts Epics/Stories, so the board has to say which ones. A matched Story
		// keeps its lane at zero cards - that emptiness is the answer. Only the
		// Overdue filter drops empty lanes, where "nothing late here" is not worth a
		// lane of its own.
		const drop_empty = !item_board && !this.state.stat_type;
		let board;
		if (epics.length) {
			board = this.epic_lanes(tasks, epics, stories, drop_empty, path);
		} else if (stories.length && (item_board || filter_on)) {
			board = this.story_lanes(tasks, stories, drop_empty, false, path);
		} else {
			board = this.section(__("Status Board"), tasks.length, this.status_columns(tasks), {
				columns_cls: "wb-columns-fill",
			});
		}
		// Nothing left to lay out at all - only reachable with a filter on, since an
		// unfiltered board always renders its (possibly empty) Status Board.
		if (!board) {
			board = this.empty_state(
				this.state.overdue_only && !this.state.stat_type
					? __("No overdue tasks here. Click the tile again to clear it.")
					: __("No open tasks under {0} · {1}. Click the tile again to clear it.", [
							__(this.state.stat_type),
							__(this.state.stat_status),
					  ])
			);
		}
		// Who-is-working-on-what across the whole team is a manager question;
		// a project member gets the status board only.
		const employee_board = this.is_manager
			? this.section(
					__("Employee Board"),
					tasks.length,
					this.employee_columns(tasks, this.data.members || [], false),
					// Collapsed until asked for - the status board answers the first
					// question. State survives re-renders via the toggle handler.
					{ open: this.state.employee_board_open, cls: "wb-employee-section" }
			  )
			: "";
		this.$body.html(`
			${this.stats_row(this.data.stats, all_tasks)}
			${board}
			${employee_board}
		`);
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

	// Project-wide Epic/Story counts, and the board's coarse filter: a tile
	// narrows the board to the Stories it stands for. Inert on a Story/Task board,
	// which is already one item deep and has no lanes to narrow.
	stats_row(stats, all_tasks) {
		// Only ever rendered with a Project picked, so the bar always shows -
		// zeroes while a fetch is in flight rather than a bar that pops in.
		stats = stats || {};
		const inert = this.data.item_type === "Story" || this.data.item_type === "Task";

		const tiles = STAT_TILES.map(({ type, status, color }) => {
			const count = (stats[type] || {})[status] || 0;
			const active =
				this.state.stat_type === type && this.state.stat_status === status && !inert;
			// Nothing to filter to: a zero tile would only ever highlight an empty
			// board, so it cannot be switched on. An already-active tile stays
			// clickable even at zero - that click is the way to clear it.
			const dead = (inert || !count) && !active;
			return `<div class="wb-stat wb-stat-${color} ${active ? "active" : ""} ${
				dead ? "inert" : ""
			}" data-type="${type}" data-status="${status}">
				<span class="wb-stat-label">
					<span class="wb-dot wb-dot-${color}"></span>${__(type)} · ${__(status)}
				</span>
				<span class="wb-stat-value">${count}</span>
			</div>`;
		}).join("");

		// Counted off the tasks on the board, not the project - the tile filters
		// what is loaded, so a count from anywhere else would not match it. Stays
		// live on a Story/Task board where the Epic/Story tiles go inert.
		const overdue_count = (all_tasks || []).filter(is_overdue).length;
		const overdue_active = this.state.overdue_only;
		const overdue_tile = `<div class="wb-stat wb-stat-red ${overdue_active ? "active" : ""} ${
			!overdue_count && !overdue_active ? "inert" : ""
		}" data-type="Overdue">
				<span class="wb-stat-label">
					<span class="wb-dot wb-dot-red"></span>${__("Overdue")}
				</span>
				<span class="wb-stat-value">${overdue_count}</span>
			</div>`;

		return `<div class="wb-stats">${tiles}${overdue_tile}</div>`;
	}

	empty_state(message) {
		return `<div class="wb-empty">${frappe.utils.escape_html(message)}</div>`;
	}

	// columns_cls: the status board has a fixed set of columns, so they share the
	// full width. The employee board has one per member and stays scrollable.
	// body_cls: an Epic section holds a stack of Story lanes rather than a row of
	// columns, so it opts out of the flex row .wb-columns lays down.
	section(
		title,
		count,
		columns_html,
		{ open = true, cls = "", columns_cls = "", badge = "", body_cls = "wb-columns" } = {}
	) {
		return `<details class="wb-section ${cls}" ${open ? "open" : ""}>
			<summary class="wb-section-title">${frappe.utils.escape_html(title)}
				<span class="wb-count">${count}</span>${badge}</summary>
			<div class="${body_cls} ${columns_cls}">${columns_html}</div>
		</details>`;
	}

	// Epic > Story > cards. Driven off the server's Epic list rather than off the
	// Stories, so an Epic with no Stories at all still gets a block - otherwise the
	// board would show fewer blocks than the tile above it counted. Same reason a
	// Story with no open Task keeps its lane. Everything starts collapsed; the
	// counts on the headers are what the board is read for first - except on the
	// chain down to a picked item, which opens so the searched-for thing is visible.
	epic_lanes(tasks, epics, stories, drop_empty, path) {
		return epics
			.map((epic) => {
				const own_stories = stories.filter((story) => story.epic === epic.name);
				const own = tasks.filter((task) =>
					own_stories.some((story) => story.name === task.parent_task)
				);
				const lanes = own_stories.length
					? this.story_lanes(own, own_stories, drop_empty, true, path)
					: `<div class="wb-column-empty">${__("No stories")}</div>`;
				const pill = epic.status
					? `<span class="wb-pill wb-pill-${status_color(epic.status)}">${__(epic.status)}</span>`
					: "";
				return this.section(epic.subject || epic.name, own.length, lanes, {
					open: path.has(epic.name),
					cls: "wb-epic-section",
					body_cls: "wb-epic-body",
					badge: `${pill}<span class="wb-lane-link wb-card" data-name="${frappe.utils.escape_html(
						epic.name
					)}">${frappe.utils.escape_html(epic.name)}</span>`,
				});
			})
			.join("");
	}

	// One Status Board per Story. A Story with no open Tasks still gets a lane - its
	// status is the point of the lane, and an absent lane would read as "no such
	// Story" rather than "nothing open in it".
	// Lanes start collapsed - the header carries the Story's status and card count,
	// which is what the board is scanned for; the cards are what you open one for.
	// nested: the lane sits inside an Epic section, which already names the Epic.
	story_lanes(tasks, stories, drop_empty, nested = false, path = new Set()) {
		return stories
			.filter((story) => !drop_empty || tasks.some((task) => task.parent_task === story.name))
			.map((story) => {
				const own = tasks.filter((task) => task.parent_task === story.name);
				// Which Epic this Story sits under - only sent for the project-wide
				// board, where nothing else on screen names it.
				const epic =
					story.epic_subject && !nested
						? `<span class="wb-lane-epic">${frappe.utils.escape_html(story.epic_subject)}</span>`
						: "";
				// Stories raised from an Issue (custom/issue.py) link back to it -
				// its own class, so the click routes to Issue and not to the Task
				// the rest of the lane header points at.
				const issue = story.issue
					? `<span class="wb-issue-link" data-issue="${frappe.utils.escape_html(
							story.issue
					  )}" title="${__("Open Issue")}">${frappe.utils.escape_html(story.issue)}</span>`
					: "";
				return this.section(
					story.subject || story.name,
					own.length,
					this.status_columns(own),
					{
						open: path.has(story.name),
						columns_cls: "wb-columns-fill",
						// wb-card so the existing card handler routes to the Story's form;
						// the lane-link handler stops that click from also toggling the lane.
						badge: `${epic}<span class="wb-pill wb-pill-${status_color(story.status)}">${__(
							story.status
						)}</span>
						<span class="wb-lane-link wb-card" data-name="${frappe.utils.escape_html(
							story.name
						)}">${frappe.utils.escape_html(story.name)}</span>${issue}`,
					}
				);
			})
			.join("");
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
		const cards = tasks.length
			? tasks.map((t) => this.card(t, show_project, !!member)).join("")
			: `<div class="wb-column-empty">${__("No tasks")}</div>`;
		return `<div class="wb-column wb-column-${color}">
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
