import logging
import re
from datetime import UTC, datetime

from django.conf import settings

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# settings.BASE_DIR is the lgsf_web package dir; data/ lives alongside manage.py, one level up
DATA_DIR = settings.LGSF_DATA_DIR

VERBOSITY_TO_LOG_LEVEL = {
    0: logging.ERROR,
    1: logging.WARNING,
    2: logging.INFO,
    3: logging.DEBUG,
}


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).date()


def clean_text(text):
    # drop NUL/control bytes Postgres rejects, and lone surrogates pypdf sometimes emits
    text = text.encode("utf-8", "surrogatepass").decode("utf-8", "ignore")
    return _CONTROL_CHARS_RE.sub("", text)
