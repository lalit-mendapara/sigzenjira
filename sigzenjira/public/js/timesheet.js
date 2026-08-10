// Only Task and Sub-task are real work-logging leaves in our hierarchy;
// Epic/Story's Actual Time is a rollup only (see sigzenjira/events/timesheet.py).
frappe.ui.form.on("Timesheet", {
	onload: function (frm) {
		frm.set_query("task", "time_logs", function () {
			console.log("Setting task query for timesheet");
			return {
				filters: {
					custom_task_work_item_type: ["in", ["Task", "Sub-task"]],
				},
			};
		});
	},

	before_submit: function (frm) {
		frappe.validated = false;

		return frappe.call({
			method: "sigzenjira.events.timesheet.check_over_budget",
			args: { timesheet_name: frm.doc.name },
		}).then((r) => {
			const warnings = r.message || [];
			if (!warnings.length) {
				frappe.validated = true;
				return;
			}

			const w = warnings[0];
			const more = warnings.length > 1 ? __(" ({0} more task(s) also over budget.)", [warnings.length - 1]) : "";

			const dialog = new frappe.ui.Dialog({
				title: __("Hours Exceed Budget"),
				fields: [
					{
						fieldtype: "HTML",
						options: `<p>${__("{0}: Budgeted Hours {1}h, Remaining Hours {2}h.{3}", [
							frappe.utils.escape_html(w.subject),
							w.expected_time,
							w.remaining,
							more,
						])}</p>`,
					},
				],
				primary_action_label: __("Request Additional Hours"),
				primary_action: function () {
					dialog.hide();
					frappe.new_doc("Additional Hours Request", { task: w.task });
				},
			});
			dialog.show();
		});
	},
});

// Mirrors force_is_billable_from_task / set_row_non_billable_hours
// (sigzenjira/events/timesheet.py) on screen. Both of those are the authority -
// they run on every save regardless of what happened here - but they only run on
// save, so without this the row shows a stale Billable tick and a blank
// Non-Billable figure for the whole time the user is filling the timesheet in.
frappe.ui.form.on("Timesheet Detail", {
	task: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		// A row with no task keeps whatever the user ticked by hand, same
		// carve-out force_is_billable_from_task makes for plain activity logging.
		if (!row.task) return;

		frappe.db.get_value("Task", row.task, "custom_task_is_billable", (task) => {
			frappe.model.set_value(cdt, cdn, "is_billable", task && task.custom_task_is_billable ? 1 : 0);
		});
	},

	hours: set_non_billable_hours,
	billing_hours: set_non_billable_hours,
	is_billable: set_non_billable_hours,
});

function set_non_billable_hours(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(
		cdt,
		cdn,
		"custom_timesheet_detail_non_billable_hours",
		flt(row.hours) - flt(row.billing_hours)
	);
}
