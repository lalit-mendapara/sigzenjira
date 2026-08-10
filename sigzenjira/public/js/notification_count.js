// Shows unread Notification Log count as a badge on the sidebar "Notification" item.
// Core frappe only toggles a seen/unseen dot there (see frappe/ui/sidebar/sidebar.js
// add_standard_items + notifications.js toggle_notification_icon), so the count is ours.
// ponytail: DOM-patch the core sidebar item; no core fork, no new doctype, no custom API.
frappe.provide("sigzenjira");

sigzenjira.refresh_notification_count = function () {
	if (frappe.session.user === "Guest") return;

	frappe.db
		// frappe.db.count reads args.filters - a bare filter dict here counts every row.
		.count("Notification Log", { filters: { for_user: frappe.session.user, read: 0 } })
		.then((count) => {
			// The item stays hidden until frappe.ui.Notifications un-hides it, so this
			// can run before the anchor exists - the route-change refresh catches up.
			let $anchor = $(".sidebar-notification .item-anchor");
			if (!$anchor.length) return;

			let $badge = $anchor.find(".sidebar-item-suffix");
			if (!$badge.length) {
				$badge = $("<span class='sidebar-item-suffix'></span>").insertAfter(
					$anchor.find(".sidebar-item-label")
				);
			}
			$badge.text(count > 99 ? "99+" : count).toggle(count > 0);
		});
};

$(document).on("app_ready", () => {
	sigzenjira.refresh_notification_count();
	frappe.realtime.on("notification", () => sigzenjira.refresh_notification_count());
	frappe.router.on("change", () => sigzenjira.refresh_notification_count());
});

// Core only publishes realtime on notification *create*, never on read - mark_as_read /
// mark_all_as_read just db.set_value (see notification_log.py). So marking read leaves the
// badge stale: "mark all as read" and the per-item .mark-as-read dot both skip navigation.
// ponytail: capture phase so the dot's stopImmediatePropagation can't skip us; 400ms because
// core drops the frappe.call promise, leaving nothing to await.
document.addEventListener(
	"click",
	(e) => {
		if (e.target.closest(".notification-item, .mark-all-read"))
			setTimeout(sigzenjira.refresh_notification_count, 400);
	},
	true
);
