// Only Task and Sub-task are real work-logging leaves in our hierarchy;
// Epic/Story's Actual Time is a rollup only (see sigzenjira/events/timesheet.py).
frappe.ui.form.on("Timesheet", {
	onload: function (frm) {
		frm.set_query("task", "time_logs", function () {
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
