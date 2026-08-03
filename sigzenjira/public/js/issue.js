// The server never guesses a billable default - it only clamps. This is the
// only thing that pre-fills the box in the Desk. A project set via
// route_options/defaults fires no change event, hence the onload_post_render
// path as well as the field handler.
function seed_billable_from_source(frm) {
	if (!frm.doc.project) {
		return;
	}
	frappe.db.get_value("Project", frm.doc.project, "custom_is_billable").then((r) => {
		frm.set_value("custom_is_billable", cint(r.message && r.message.custom_is_billable));
	});
}

frappe.ui.form.on("Issue", {
	onload_post_render(frm) {
		if (frm.is_new()) {
			seed_billable_from_source(frm);
		}
	},

	project(frm) {
		// Only while new. On a saved document this would silently overwrite a
		// deliberate choice - a non-billable Issue linked to a billable Project
		// (or vice versa) is legitimate, and re-picking Project must not
		// quietly flip it.
		if (frm.is_new()) {
			seed_billable_from_source(frm);
		}
	},

	refresh(frm) {
		frm.remove_custom_button("Task", "Create");

		if (frm.doc.status !== "Closed") {
			frm.add_custom_button(
				__("Story"),
				() => {
					frappe.call({
						method: "sigzenjira.custom.issue.make_story",
						args: { issue_name: frm.doc.name },
						callback: (r) => {
							if (r.message) {
								frappe.set_route("Form", "Task", r.message);
							}
						},
					});
				},
				__("Create")
			);
		}
	},
});
