"""Cancellation plumbing shared by the scrape and download jobs."""


class StopRequested(Exception):
    """Raised when the user cancels a scrape or a download."""


def check_stop(should_stop):
    """Raise StopRequested if the caller asked the job to stop."""
    if should_stop and should_stop():
        raise StopRequested("Cancelled.")
