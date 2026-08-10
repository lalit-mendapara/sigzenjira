from sigzenjira.setup import create_ecd_notifications


def execute():
	# Nothing is re-applied on migrate (this app has no fixtures hook), so the
	# six Notification records reach already-installed sites only through here.
	create_ecd_notifications()
