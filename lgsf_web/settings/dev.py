# dev.py
# Set things here that we want to always be true in dev
# but don't make sense in any deployed environment

from .base import *  # noqa
import contextlib

DEBUG = True

INSTALLED_APPS += ("debug_toolbar",)
MIDDLEWARE = [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
] + MIDDLEWARE

with contextlib.suppress(ImportError):
    from .local import *
