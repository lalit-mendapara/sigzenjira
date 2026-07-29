// Kanban cards render Link fields via frappe.format(), which shows the
// Project's title (project_name) instead of its id only if
// frappe._link_titles is already warm (core list views populate it
// per-row; the Kanban board's lightweight card fetch never does). Prime it
// once per view load and re-render so "project" shows its name, not id.
frappe.listview_settings["Task"] = frappe.listview_settings["Task"] || {};
frappe.listview_settings["Task"].onload = function (listview) {
	frappe.db.get_list("Project", { fields: ["name", "project_name"], limit_page_length: 0 }).then((projects) => {
		projects.forEach((p) => frappe.utils.add_link_title("Project", p.name, p.project_name));
		// Kanban's update() diffs card data and skips re-render when the
		// underlying doc hasn't changed, so a plain refresh() won't pick up
		// the now-warm title cache. Drop the board so render() rebuilds
		// every card from scratch.
		if (listview.kanban) listview.kanban = null;
		listview.refresh();
	});
};
