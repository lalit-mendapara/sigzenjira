// Project Billing - review and adjust billable hours per project.
//
// The tree is Project > Epic > Story > Task > Sub-task > timesheet rows. Only
// the timesheet rows are editable: every level above them shows the stored
// rollup that recompute_actual_time maintains, so typing into one would be
// editing a total rather than a fact.

frappe.pages["project-billing"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Project Billing"),
		single_column: true,
	});

	new ProjectBilling(page);
};

class ProjectBilling {
	constructor(page) {
		this.page = page;
		this.rows = [];
		// fieldname -> pending billable-hours value. Nothing reaches the server
		// until Save, so a mistyped figure costs nothing until it is committed.
		this.pending = {};
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
			label: __("Project"),
			fieldtype: "Select",
			change: () => {
				// A person who billed the old project is unlikely to have billed
				// this one, and a stale value would silently filter every row away.
				this.employee_field.set_value("");
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
			change: () => this.refresh(),
		});

		this.employee_field = this.page.add_field({
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
			get_query: () => {
				const names = this.employees.map((e) => e.name);
				// No project loaded yet, or nobody has billed it: offer nothing
				// rather than the whole Employee table.
				return { filters: { name: ["in", names.length ? names : [""]] } };
			},
			change: () => this.refresh(),
		});

		this.from_date_field = this.page.add_field({
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			change: () => this.refresh(),
		});

		this.to_date_field = this.page.add_field({
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			change: () => this.refresh(),
		});

		this.save_button = this.page.set_primary_action(__("Save Changes"), () => this.save());
		this.set_dirty(false);
	}

	make_body() {
		this.body = $('<div class="project-billing"></div>').appendTo(this.page.main);
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

	set_employee_options(employees) {
		this.employees = employees || [];

		// Anyone who billed hours here stays selectable regardless of which company
		// employs them - a cross-company timesheet is still money on this invoice.
		const selected = this.employee_field.get_value();
		if (selected && !this.employees.some((e) => e.name === selected)) {
			this.employee_field.set_value("");
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
		};
	}

	refresh() {
		const filters = this.filters();
		if (!filters.project) {
			this.employees = [];
			this.render_message(__("Select a project to review its billable hours."));
			return;
		}

		// Discarded deliberately: the figures are about to be replaced, so keeping
		// edits keyed to rows that may not survive the reload would silently apply
		// them to a different set than the one they were typed against.
		this.pending = {};
		this.set_dirty(false);

		frappe.call({ method: this.method("get_project_billing"), args: filters }).then((r) => {
			const data = r.message || {};
			this.rows = data.rows || [];
			this.set_employee_options(data.employees);
			this.render(data);
		});
	}

	render_message(message) {
		this.body.html(`<div class="project-billing-empty">${frappe.utils.escape_html(message)}</div>`);
	}

	render(data) {
		if (!this.rows.length) {
			this.render_message(__("No submitted timesheet hours on this project for that period."));
			return;
		}

		const totals = data.totals || {};
		const project_totals = data.project_totals || {};

		this.body.html(`
			<div class="project-billing-summary">
				${this.summary_tile(__("Hours in view"), totals.hours)}
				${this.summary_tile(__("Billable in view"), totals.billing_hours)}
				${this.summary_tile(__("Non-billable in view"), totals.non_billable_hours)}
				${this.summary_tile(
					__("Project billable (all time)"),
					project_totals.custom_project_billable_hours
				)}
				${this.summary_tile(
					__("Project non-billable (all time)"),
					project_totals.custom_project_non_billable_hours
				)}
			</div>
			<div class="project-billing-table-wrapper">
				<table class="project-billing-table">
					<thead>
						<tr>
							<th class="pb-work">${__("Work Item / Time Log")}</th>
							<th class="pb-num">${__("Hours")}</th>
							<th class="pb-num">${__("Billable")}</th>
							<th class="pb-num">${__("Non-Billable")}</th>
							<th class="pb-read">${__("Read")}</th>
						</tr>
					</thead>
					<tbody></tbody>
				</table>
			</div>
		`);

		this.render_rows();
		this.bind_row_events();
	}

	summary_tile(label, value) {
		return `
			<div class="project-billing-tile">
				<div class="project-billing-tile-label">${frappe.utils.escape_html(label)}</div>
				<div class="project-billing-tile-value">${format_number(value || 0, null, 2)}</div>
			</div>
		`;
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
		const body = this.body.find("tbody");
		body.empty();

		this.visible_rows().forEach((row) => {
			body.append(row.row_type === "task" ? this.task_row_html(row) : this.detail_row_html(row));
		});
	}

	task_row_html(row) {
		const has_children = this.has_children(row);
		const caret = has_children
			? `<span class="pb-caret">${this.collapsed.has(row.name) ? "&#9656;" : "&#9662;"}</span>`
			: '<span class="pb-caret pb-caret-empty"></span>';

		const badge = row.work_item_type
			? `<span class="pb-badge pb-badge-${row.work_item_type.toLowerCase().replace("-", "")}">${
					row.work_item_type
			  }</span>`
			: "";

		const link = row.name
			? `<a href="/app/task/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(row.label)}</a>`
			: frappe.utils.escape_html(row.label);

		return `
			<tr class="pb-task-row" data-name="${frappe.utils.escape_html(row.name)}">
				<td class="pb-work" style="padding-left: ${12 + row.indent * 20}px">
					${caret}${badge}${link}
					${row.is_billable ? '<span class="pb-billable-dot" title="Billable"></span>' : ""}
				</td>
				<td class="pb-num">${format_number(row.hours, null, 2)}</td>
				<td class="pb-num">${format_number(row.billing_hours, null, 2)}</td>
				<td class="pb-num">${format_number(row.non_billable_hours, null, 2)}</td>
				<td class="pb-read"></td>
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

		const billing_cell = editable
			? `<input type="number" class="pb-input" step="0.01" min="0" max="${row.hours}"
					value="${format_number(billing_hours, null, 2)}" data-name="${row.name}">`
			: format_number(billing_hours, null, 2);

		const who = row.employee_name ? ` &middot; ${frappe.utils.escape_html(row.employee_name)}` : "";
		const label = `${frappe.utils.escape_html(row.label)}${who} &middot; ${frappe.datetime.str_to_user(
			row.from_time
		)}`;

		return `
			<tr class="pb-detail-row ${pending === undefined ? "" : "pb-dirty"}" data-name="${row.name}">
				<td class="pb-work" style="padding-left: ${12 + row.indent * 20}px">
					<a href="/app/timesheet/${encodeURIComponent(row.timesheet)}">${label}</a>
					${row.locked ? `<span class="pb-lock" title="${__("Invoiced")}">&#128274;</span>` : ""}
				</td>
				<td class="pb-num">${format_number(row.hours, null, 2)}</td>
				<td class="pb-num pb-editable">${billing_cell}</td>
				<td class="pb-num">${format_number(non_billable, null, 2)}</td>
				<td class="pb-read">
					<input type="checkbox" class="pb-read-check" data-name="${row.name}"
						${row.mark_as_read ? "checked" : ""}>
				</td>
			</tr>
		`;
	}

	has_children(task_row) {
		const index = this.rows.indexOf(task_row);
		const next = this.rows[index + 1];
		return !!next && next.indent > task_row.indent;
	}

	bind_row_events() {
		this.body.on("click", ".pb-task-row .pb-caret", (event) => {
			const name = $(event.currentTarget).closest("tr").data("name");
			if (this.collapsed.has(name)) {
				this.collapsed.delete(name);
			} else {
				this.collapsed.add(name);
			}
			this.render_rows();
		});

		this.body.on("change", ".pb-input", (event) => {
			const input = $(event.currentTarget);
			const name = input.data("name");
			const row = this.rows.find((r) => r.name === name);
			const value = flt(input.val());

			// Checked here as well as on the server so a typo is caught before it
			// costs a round trip; update_billing_hours re-checks both bounds because
			// this method is whitelisted and reachable without the page.
			if (value < 0 || value > flt(row.hours)) {
				frappe.show_alert({
					message: __("Billable hours must be between 0 and {0}.", [row.hours]),
					indicator: "red",
				});
				input.val(format_number(row.billing_hours, null, 2));
				return;
			}

			if (value === flt(row.billing_hours)) {
				delete this.pending[name];
			} else {
				this.pending[name] = value;
			}

			this.set_dirty(Object.keys(this.pending).length > 0);
			this.render_rows();
		});

		this.body.on("change", ".pb-read-check", (event) => {
			const input = $(event.currentTarget);
			const name = input.data("name");
			const value = input.is(":checked") ? 1 : 0;

			frappe
				.call({
					method: this.method("set_mark_as_read"),
					args: { names: [name], value: value },
				})
				.then(() => {
					const row = this.rows.find((r) => r.name === name);
					if (row) row.mark_as_read = value;
				});
		});
	}

	set_dirty(dirty) {
		this.page.btn_primary.toggleClass("hide", !dirty);
	}

	save() {
		const updates = Object.keys(this.pending).map((name) => ({
			name: name,
			billing_hours: this.pending[name],
		}));

		if (!updates.length) return;

		frappe
			.call({
				method: this.method("update_billing_hours"),
				args: { updates: updates },
				freeze: true,
				freeze_message: __("Updating billable hours..."),
			})
			.then((r) => {
				if (!r.message) return;
				frappe.show_alert({
					message: __("{0} row(s) updated.", [r.message.updated]),
					indicator: "green",
				});
				// Reloaded rather than patched in place: one edit moves the whole
				// chain of rollups above it, so every ancestor row on screen is stale.
				this.refresh();
			});
	}
}
