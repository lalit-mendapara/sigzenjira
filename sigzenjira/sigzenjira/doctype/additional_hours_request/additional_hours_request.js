// Copyright (c) 2026, sigzenjira and contributors
// For license information, please see license.txt

frappe.ui.form.on("Additional Hours Request", {
	onload: function (frm) {
		frm.set_query("task", function () {
			return {
				filters: {
					custom_work_item_type: "Task",
				},
			};
		});
	},
});
