// Project Billing - review and adjust billable hours per project.
//
// The tree is Project > Epic > Story > Task > Sub-task > timesheet rows. Only
// the timesheet rows are editable: every level above them shows the stored
// rollup that recompute_actual_time maintains, so typing into one would be
// editing a total rather than a fact.
//
// The layout deliberately mirrors pulse_sigzen's Pulse Project Billing Summary
// (same twelve columns, same sticky edges, same pinned totals strip) so a
// reviewer moving between the two pages reads the same shape. Everything class
// is prefixed sjb- because frappe keeps a visited page's assets loaded: sharing
// pulse's unprefixed class names and #report-output id would have the two pages
// styling and querying each other.
//
// What is deliberately not carried over: pulse's Project Manager Mapping, and
// with it the Unmapped Employees filter. Who may see a project here is settled
// by BILLING_ROLES plus permission/project.py, not by a mapping table.

frappe.pages["project-billing"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Project Billing"),
		single_column: true,
	});

	new ProjectBilling(page);
};

// Rows shown before the table starts scrolling internally. Past this the header
// stays put and the body scrolls, so the totals strip never walks off screen.
const SJB_VISIBLE_ROWS = 17;

class ProjectBilling {
	constructor(page) {
		this.page = page;
		this.rows = [];
		// name -> pending billable-hours value. Nothing reaches the server until
		// Update, so a mistyped figure costs nothing until it is committed.
		this.pending = {};
		this.pending_read = {};
		this.collapsed = new Set();
		// Every billable project the user may see, kept so the Company filter can
		// narrow the Project list without a second server round trip.
		this.all_projects = [];
		// Employees with submitted hours on the project currently in view. Filled
		// by each load, so the dropdown can only ever offer people who billed here.
		this.employees = [];

		this.make_filters();
		this.make_body();
		this.bootstrap();
	}

	make_filters() {
		this.page.page_form.removeClass("hide").addClass("sjb-filters");

		// Company narrows the Project list and nothing else. It deliberately does
		// not reach the Employee filter: see set_employee_options.
		this.company_field = this.page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			change: () => this.set_project_options(),
		});

		this.project_field = this.page.add_field({
			fieldname: "project",
			label: __("Project") + " *",
			fieldtype: "Select",
			change: () => {
				// A person who billed the old project is unlikely to have billed
				// this one, and a stale value would silently filter every row away.
				this.clear_employee();
				this.project_field.$input.removeClass("sjb-invalid");
				this.refresh();
			},
		});

		// Re-roots the tree at the chosen level: pick Story and every Story is a
		// top-level row with its own Tasks, Sub-tasks and time logs still nested
		// and collapsible underneath it.
		this.work_item_type_field = this.page.add_field({
			fieldname: "work_item_type",
			label: __("Work Item Type"),
			fieldtype: "Select",
		});

		// Select, not a Link on Employee: a Link's get_query filters are advisory -
		// the control caches results per doctype+term and the search endpoint is
		// still the whole Employee table, so the dropdown leaked people who never
		// billed here. The server already ships the exact list; offer only that.
		this.employee_field = this.page.add_field({
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Select",
			options: [{ value: "", label: __("All Employees") }],
			// Reloads on pick, like Project: the date fields wait for Apply because
			// a range is two edits, but picking a person is one and complete.
			change: () => this.refresh(),
		});

		this.from_date_field = this.page.add_field({
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		});

		this.to_date_field = this.page.add_field({
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		});

		// Off, the page is the working list: rows already settled are out of the
		// way. On, it is the record of what was settled.
		this.is_updated_field = this.page.add_field({
			fieldname: "is_updated",
			label: __("Is Updated"),
			fieldtype: "Check",
		});

		const $checks = $('<div class="sjb-filter-checks"></div>');
		$checks.append(this.control_wrapper(this.is_updated_field));
		this.control_wrapper(this.employee_field).after($checks);
		$checks.find(".frappe-control").removeClass("col-md-2");

		this.page.add_break();
		this.make_buttons();
	}

	make_buttons() {
		this.apply_button = this.page.add_field({
			fieldname: "apply_btn",
			label: __("Apply Filters"),
			fieldtype: "Button",
		});
		this.refresh_button = this.page.add_field({
			fieldname: "refresh_btn",
			label: __("Refresh"),
			fieldtype: "Button",
		});
		this.update_button = this.page.add_field({
			fieldname: "update_btn",
			label: __("Update Timesheet Hours"),
			fieldtype: "Button",
		});

		const $row = $('<div class="sjb-buttons-row"></div>');
		$row.append(this.control_wrapper(this.apply_button))
			.append(this.control_wrapper(this.refresh_button))
			.append(this.control_wrapper(this.update_button));
		this.page.page_form.find(".clearfix").last().after($row);
		$row.find(".frappe-control").removeClass("col-md-2");

		this.apply_button.$input.removeClass("btn-default btn-xs").addClass("btn-success btn-sm");
		this.refresh_button.$input
			.removeClass("btn-default btn-xs")
			.addClass("btn-default btn-sm sjb-icon-btn")
			.html('<i class="fa fa-refresh"></i>')
			.attr("title", __("Refresh"))
			.attr("aria-label", __("Refresh"));
		this.update_button.$input
			.removeClass("btn-default btn-xs")
			.addClass("btn-primary btn-sm")
			.html('<i class="fa fa-save"></i> ' + __("Update Timesheet Hours"));

		this.apply_button.$input.on("click", () => this.refresh());
		this.refresh_button.$input.on("click", () => this.refresh());
		this.update_button.$input.on("click", () => this.save());
	}

	control_wrapper(field) {
		return field.$wrapper ? field.$wrapper.closest(".frappe-control") : $(field.wrapper);
	}

	make_body() {
		this.page.main.addClass("sjb-page-main");
		this.body = $(`
			<div class="sjb-wrapper">
				<div class="sjb-report"></div>
				<div class="sjb-totals"></div>
			</div>
		`).appendTo(this.page.main);
		this.report = this.body.find(".sjb-report");
		this.totals = this.body.find(".sjb-totals");
		this.bind_row_events();
	}

	bootstrap() {
		frappe.call({ method: this.method("get_bootstrap") }).then((r) => {
			const data = r.message || {};
			this.all_projects = data.projects || [];

			this.work_item_type_field.df.options = [{ value: "", label: __("Whole hierarchy") }].concat(
				(data.work_item_types || []).map((t) => ({ value: t, label: __(t) }))
			);
			this.work_item_type_field.refresh();

			if (!this.all_projects.length) {
				this.render_message(
					__("No billable projects available to you. Tick Billable on a Project first.")
				);
				return;
			}

			this.set_project_options();
		});
	}

	set_project_options() {
		const company = this.company_field.get_value();
		const matching = company
			? this.all_projects.filter((p) => p.company === company)
			: this.all_projects;

		const options = matching.map((p) => ({ value: p.name, label: p.project_name || p.name }));

		this.project_field.df.options = [{ value: "", label: __("Select a project") }].concat(options);
		this.project_field.refresh();

		// The project in view may not belong to the newly picked company. Clearing
		// it drives the project change handler, which reloads and drops the
		// employee too, so no separate refresh is needed here.
		const selected = this.project_field.get_value();
		if (selected && !matching.some((p) => p.name === selected)) {
			this.project_field.set_value("");
		}
	}

	// set_value fires the field's change handler, which would re-enter refresh and
	// load the board a second time. Clearing the control directly keeps the reload
	// that follows the only one.
	clear_employee() {
		this.employee_field.value = "";
		this.employee_field.set_input("");
	}

	set_employee_options(employees) {
		this.employees = employees || [];

		// Anyone who billed hours here stays selectable regardless of which company
		// employs them - a cross-company timesheet is still money on this invoice.
		const selected = this.employee_field.get_value();
		this.employee_field.df.options = [{ value: "", label: __("All Employees") }].concat(
			this.employees.map((e) => ({ value: e.name, label: e.employee_name || e.name }))
		);
		this.employee_field.refresh();

		// Refreshing options blanks the input, so a still-valid pick is put back;
		// one who is neither on the project nor billed it is dropped rather than
		// silently filtering every row away.
		if (selected && this.employees.some((e) => e.name === selected)) {
			this.employee_field.set_input(selected);
		} else if (selected) {
			this.clear_employee();
		}
	}

	method(name) {
		return `sigzenjira.sigzenjira.page.project_billing.project_billing.${name}`;
	}

	filters() {
		return {
			project: this.project_field.get_value(),
			work_item_type: this.work_item_type_field.get_value(),
			employee: this.employee_field.get_value(),
			from_date: this.from_date_field.get_value(),
			to_date: this.to_date_field.get_value(),
			is_updated: this.is_updated_field.get_value() ? 1 : 0,
		};
	}

	refresh() {
		const filters = this.filters();
		if (!filters.project) {
			this.set_employee_options([]);
			this.project_field.$input.addClass("sjb-invalid");
			this.render_message(__("Select a project to review its billable hours."));
			return;
		}

		// Discarded deliberately: the figures are about to be replaced, so keeping
		// edits keyed to rows that may not survive the reload would silently apply
		// them to a different set than the one they were typed against.
		this.pending = {};
		this.pending_read = {};

		frappe.call({ method: this.method("get_project_billing"), args: filters }).then((r) => {
			const data = r.message || {};
			this.rows = data.rows || [];
			this.set_employee_options(data.employees);
			this.render(data);
		});
	}

	render_message(message) {
		this.report.html(`<div class="sjb-no-data">${frappe.utils.escape_html(message)}</div>`);
		this.totals.empty();
		this.fit();
	}

	render(data) {
		if (!this.rows.length) {
			this.render_message(__("No submitted timesheet hours on this project for that period."));
			return;
		}

		this.report.html(`
			<div class="sjb-table-wrapper">
				<table class="sjb-table">
					<thead>
						<tr>
							<th>${__("Work Item / Time Log")}</th>
							<th title="${__("Billable hours rolled up on the work item")}">TBH</th>
							<th title="${__("Non-billable hours rolled up on the work item")}">TNBH</th>
							<th>${__("Employee")}</th>
							<th>${__("Timesheet Id")}</th>
							<th>${__("Timesheet Date")}</th>
							<th>${__("Activity Type")}</th>
							<th>${__("TI desc")}</th>
							<th>${__("Total hrs")}</th>
							<th title="${__("Billable hours")}">BH</th>
							<th title="${__("Non billable hours")}">NBH</th>
							<th>${__("Mark as read")}</th>
						</tr>
					</thead>
					<tbody></tbody>
				</table>
			</div>
		`);

		this.render_rows();
		this.render_totals(data.totals || {});
	}

	render_totals(totals) {
		// Only the timesheet columns are totalled. Summing the work item columns
		// would count an hour once per ancestor: an Epic's rollup already contains
		// its Stories', which already contain their Tasks'.
		this.totals.html(`
			<div class="sjb-totals-inner">
				<table class="sjb-totals-table">
					<tr>
						<td><strong>${__("Total Hours")}</strong></td>
						<td></td>
						<td></td>
						<td></td>
						<td></td>
						<td></td>
						<td></td>
						<td></td>
						<td><strong>${format_number(totals.hours || 0, null, 2)}</strong></td>
						<td><strong>${format_number(totals.billing_hours || 0, null, 2)}</strong></td>
						<td><strong>${format_number(totals.non_billable_hours || 0, null, 2)}</strong></td>
						<td></td>
					</tr>
				</table>
			</div>
		`);

		// The strip is a second table outside the scrolling area, so it has to be
		// dragged along by hand or it drifts out of column as soon as the body
		// scrolls sideways.
		const $wrapper = this.report.find(".sjb-table-wrapper");
		const $strip = this.totals.find(".sjb-totals-inner");
		$wrapper.off("scroll.sjbSync").on("scroll.sjbSync", () => $strip.scrollLeft($wrapper.scrollLeft()));
		$strip.off("scroll.sjbSync").on("scroll.sjbSync", () => $wrapper.scrollLeft($strip.scrollLeft()));

		this.fit();
	}

	// A row is hidden when any task above it is collapsed. Tracked by walking the
	// flat list and remembering the shallowest collapsed depth still in force,
	// which is cheaper than rebuilding the tree client-side just to hide things.
	visible_rows() {
		let hidden_from = null;
		return this.rows.filter((row) => {
			if (hidden_from !== null && row.indent > hidden_from) return false;

			hidden_from = null;
			if (row.row_type === "task" && this.collapsed.has(row.name)) {
				hidden_from = row.indent;
			}
			return true;
		});
	}

	render_rows() {
		const body = this.report.find("tbody");
		body.empty();

		this.visible_rows().forEach((row) => {
			body.append(row.row_type === "task" ? this.task_row_html(row) : this.detail_row_html(row));
		});

		this.refresh_toggle_states();
		this.fit();
	}

	task_row_html(row) {
		const has_children = this.has_children(row);
		const caret = has_children
			? `<i class="fa ${
					this.collapsed.has(row.name) ? "fa-chevron-right" : "fa-chevron-down"
			  } sjb-caret"></i>`
			: '<i class="sjb-caret sjb-caret-empty"></i>';

		const badge = row.work_item_type
			? `<span class="sjb-badge sjb-badge-${row.work_item_type.toLowerCase().replace("-", "")}">${
					row.work_item_type
			  }</span>`
			: "";

		const link = row.name
			? `<a class="sjb-link" href="/app/task/${encodeURIComponent(
					row.name
			  )}">${frappe.utils.escape_html(row.label)}</a>`
			: frappe.utils.escape_html(row.label);

		// Every editable row under this work item at once. The subtree can be
		// hundreds of rows deep, and ticking them one by one is the whole reason
		// people stopped using the list view for this.
		const toggle = `<input type="checkbox" class="sjb-read-all" data-name="${frappe.utils.escape_html(
			row.name
		)}">`;

		return `
			<tr class="sjb-row sjb-task-row sjb-indent-0" data-name="${frappe.utils.escape_html(row.name)}">
				<td class="sjb-work" title="${frappe.utils.escape_html(row.label)}"
					style="padding-left: ${8 + row.indent * 16}px">
					${caret}${badge}${link}
					${row.is_billable ? '<span class="sjb-billable-dot" title="Billable"></span>' : ""}
				</td>
				<td class="sjb-num">${format_number(row.billing_hours, null, 2)}</td>
				<td class="sjb-num">${format_number(row.non_billable_hours, null, 2)}</td>
				<td></td>
				<td></td>
				<td></td>
				<td></td>
				<td></td>
				<td class="sjb-num">${format_number(row.hours, null, 2)}</td>
				<td></td>
				<td></td>
				<td class="sjb-read">${toggle}</td>
			</tr>
		`;
	}

	detail_row_html(row) {
		const pending = this.pending[row.name];
		const billing_hours = pending === undefined ? row.billing_hours : pending;
		const non_billable = flt(row.hours) - flt(billing_hours);
		// The page's only gate is BILLING_ROLES, checked server-side on open, so
		// anyone looking at this can edit. Only the row itself can freeze a cell.
		const editable = !row.locked && row.is_billable;
		const read = this.pending_read[row.name] === undefined ? row.mark_as_read : this.pending_read[row.name];

		const input = (cls, value) =>
			`<input type="number" class="sjb-input ${cls}" step="0.01" min="0" max="${row.hours}"
				value="${flt(value).toFixed(2)}" data-name="${row.name}">`;

		const billing_cell = editable
			? input("sjb-billable", billing_hours)
			: format_number(billing_hours, null, 2);
		const non_billable_cell = editable
			? input("sjb-non-billable", non_billable)
			: format_number(non_billable, null, 2);

		const escape = frappe.utils.escape_html;
		// Description is a Text Editor field, so it arrives as HTML. Stripped to
		// text: the cell is one line high and a stray <p> would blow it open.
		const description = strip_html(row.description || "").trim();

		return `
			<tr class="sjb-row sjb-detail-row sjb-indent-2 ${pending === undefined ? "" : "sjb-dirty"}"
				data-name="${row.name}">
				<td class="sjb-work" style="padding-left: ${8 + row.indent * 16}px">
					${row.locked ? `<span class="sjb-lock" title="${__("Invoiced")}">&#128274;</span>` : ""}
				</td>
				<td></td>
				<td></td>
				<td class="sjb-employee" title="${escape(row.employee_name || "")}">${escape(
			row.employee_name || ""
		)}</td>
				<td class="sjb-ellipsis" title="${escape(row.timesheet || "")}">
					<a class="sjb-link" href="/app/timesheet/${encodeURIComponent(row.timesheet)}">${escape(
			row.timesheet
		)}</a>
				</td>
				<td>${frappe.datetime.str_to_user(row.from_time)}</td>
				<td class="sjb-ellipsis" title="${escape(row.activity_type || "")}">${escape(
			row.activity_type || ""
		)}</td>
				<td class="sjb-ellipsis" title="${escape(description)}">${escape(description)}</td>
				<td class="sjb-num">${format_number(row.hours, null, 2)}</td>
				<td class="sjb-num">${billing_cell}</td>
				<td class="sjb-num">${non_billable_cell}</td>
				<td class="sjb-read">
					<input type="checkbox" class="sjb-read-check" data-name="${row.name}" ${read ? "checked" : ""}>
				</td>
			</tr>
		`;
	}

	has_children(task_row) {
		const index = this.rows.indexOf(task_row);
		const next = this.rows[index + 1];
		return !!next && next.indent > task_row.indent;
	}

	// The timesheet rows under a work item: every row after it, up to the next row
	// at its own depth or shallower. Read off the flat list rather than the DOM so
	// a collapsed subtree still counts.
	descendant_details(task_name) {
		const start = this.rows.findIndex((row) => row.row_type === "task" && row.name === task_name);
		if (start === -1) return [];

		const depth = this.rows[start].indent;
		const out = [];
		for (let i = start + 1; i < this.rows.length; i++) {
			const row = this.rows[i];
			if (row.indent <= depth) break;
			if (row.row_type === "timesheet") out.push(row);
		}
		return out;
	}

	read_value(row) {
		return this.pending_read[row.name] === undefined
			? (row.mark_as_read ? 1 : 0)
			: this.pending_read[row.name];
	}

	refresh_toggle_states() {
		this.report.find(".sjb-read-all").each((_, element) => {
			const $toggle = $(element);
			const children = this.descendant_details($toggle.data("name"));
			const checked = children.filter((row) => this.read_value(row)).length;
			$toggle.prop("checked", children.length > 0 && checked === children.length);
			$toggle.prop("indeterminate", checked > 0 && checked < children.length);
		});
	}

	bind_row_events() {
		this.body.on("click", ".sjb-task-row .sjb-caret", (event) => {
			const name = $(event.currentTarget).closest("tr").data("name");
			if (this.collapsed.has(name)) {
				this.collapsed.delete(name);
			} else {
				this.collapsed.add(name);
			}
			this.render_rows();
		});

		// Bound to both inputs: they are two views of one number, so whichever is
		// typed into, the other is what is left of the hours worked.
		this.body.on("change", ".sjb-billable, .sjb-non-billable", (event) => {
			const input = $(event.currentTarget);
			const name = input.data("name");
			const row = this.rows.find((r) => r.name === name);
			const typed = flt(input.val());
			const value = input.hasClass("sjb-billable") ? typed : flt(row.hours) - typed;

			// Checked here as well as on the server so a typo is caught before it
			// costs a round trip; update_billing_hours re-checks both bounds because
			// this method is whitelisted and reachable without the page.
			if (typed < 0 || typed > flt(row.hours)) {
				frappe.show_alert({
					message: __("Hours must be between 0 and {0}.", [row.hours]),
					indicator: "red",
				});
				this.render_rows();
				return;
			}

			if (value === flt(row.billing_hours)) {
				delete this.pending[name];
			} else {
				this.pending[name] = value;
			}

			this.render_rows();
		});

		this.body.on("change", ".sjb-read-check", (event) => {
			const input = $(event.currentTarget);
			const name = input.data("name");
			const row = this.rows.find((r) => r.name === name);
			const value = input.is(":checked") ? 1 : 0;

			if (row && value === (row.mark_as_read ? 1 : 0)) {
				delete this.pending_read[name];
			} else {
				this.pending_read[name] = value;
			}

			this.refresh_toggle_states();
		});

		this.body.on("change", ".sjb-read-all", (event) => {
			const input = $(event.currentTarget);
			const value = input.is(":checked") ? 1 : 0;

			this.descendant_details(input.data("name")).forEach((row) => {
				if (value === (row.mark_as_read ? 1 : 0)) {
					delete this.pending_read[row.name];
				} else {
					this.pending_read[row.name] = value;
				}
			});

			this.render_rows();
		});
	}

	// Under the row cap the table is as tall as its content and the totals strip
	// sits straight under it; past it the body scrolls and the strip stays put.
	fit() {
		requestAnimationFrame(() => {
			const $wrapper = this.report.find(".sjb-table-wrapper");
			const $table = $wrapper.find(".sjb-table");
			if (!$table.length) {
				$wrapper.css("max-height", "");
				return;
			}

			const $visible = $table.find("tbody tr");
			if ($visible.length <= SJB_VISIBLE_ROWS) {
				$wrapper.css("max-height", "");
				return;
			}

			const header = $table.find("thead").outerHeight() || 0;
			const row_height = $visible.first().outerHeight() || 28;
			$wrapper.css("max-height", header + SJB_VISIBLE_ROWS * row_height + "px");
		});
	}

	save() {
		const updates = Object.keys(this.pending).map((name) => ({
			name: name,
			billing_hours: this.pending[name],
		}));
		const read_names = Object.keys(this.pending_read);

		if (!updates.length && !read_names.length) {
			frappe.msgprint({
				title: __("No Changes"),
				message: __("No changes to update."),
				indicator: "blue",
			});
			return;
		}

		const calls = [];
		if (updates.length) {
			calls.push(
				frappe.call({
					method: this.method("update_billing_hours"),
					args: { updates: updates },
					freeze: true,
					freeze_message: __("Updating billable hours..."),
				})
			);
		}
		// Split by value rather than sent per row: two calls at most, whatever the
		// size of the subtree somebody just ticked.
		[0, 1].forEach((value) => {
			const names = read_names.filter((name) => this.pending_read[name] === value);
			if (!names.length) return;
			calls.push(
				frappe.call({
					method: this.method("set_mark_as_read"),
					args: { names: names, value: value },
					freeze: true,
				})
			);
		});

		Promise.all(calls).then(() => {
			frappe.show_alert({
				message: __("{0} row(s) updated.", [
					new Set(Object.keys(this.pending).concat(read_names)).size,
				]),
				indicator: "green",
			});
			// Reloaded rather than patched in place: one edit moves the whole
			// chain of rollups above it, so every ancestor row on screen is stale.
			this.refresh();
		});
	}
}
