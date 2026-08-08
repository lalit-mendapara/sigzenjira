// Copyright (c) 2026, sigzenjira and contributors
// For license information, please see license.txt

const HOUR_SUMMARY_FIELDS = [
	"task_allocated_hours",
	"task_actual_hours",
	"task_total_hours",
	"story",
	"story_expected_hours",
	"story_allocated_hours",
	"story_buffer_hours",
];

// Nothing here is stored - an approver opening a request days later needs the
// Task's logged hours and the Story's budget as they stand now. Written onto
// frm.doc directly (not set_value) so re-reading them never marks the form
// dirty; validate() blanks them again on the next real save.
function refresh_hour_summary(frm) {
	if (!frm.doc.task) {
		return;
	}
	frappe
		.call({
			method: "sigzenjira.sigzenjira.doctype.additional_hours_request.additional_hours_request.get_hour_summary",
			args: { task: frm.doc.task },
		})
		.then((r) => {
			Object.assign(frm.doc, r.message || {});
			HOUR_SUMMARY_FIELDS.forEach((fieldname) => frm.refresh_field(fieldname));
			// Writing straight onto frm.doc skips the dependency pass that
			// set_value would have run, so the section's depends_on
			// ("eval:doc.story") keeps it hidden on any request saved before
			// these fields existed - re-run it by hand.
			frm.layout.refresh_dependency();
		});
}

frappe.ui.form.on("Additional Hours Request", {
	refresh: refresh_hour_summary,

	task: refresh_hour_summary,

	onload: function (frm) {
		frm.set_query("task", function () {
			return {
				filters: {
					custom_task_work_item_type: "Task",
				},
			};
		});
	},
});
