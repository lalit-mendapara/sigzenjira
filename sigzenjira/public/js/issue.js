frappe.ui.form.on("Issue", {
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
