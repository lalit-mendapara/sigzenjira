frappe.ui.form.on("Project", {
	refresh(frm) {
		if (frm.is_new()) return;
		// The board reads route_options.project on show and preselects its picker.
		frm.add_custom_button(__("Work Board"), () => {
			frappe.route_options = { project: frm.doc.name };
			frappe.set_route("work-board");
		});
	},
});
