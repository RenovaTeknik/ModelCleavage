"""Small progress hooks shared by the geometry stages and isolated worker."""
from contextvars import ContextVar

_reporter = ContextVar('cut_progress', default=None)


def report(stage, completed=None, total=None):
    callback = _reporter.get()
    if callback is not None:
        callback(stage, completed, total)
