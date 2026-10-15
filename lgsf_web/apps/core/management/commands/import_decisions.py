"""
Import scraped decisions and documents from ./data/<COUNCIL>/Decisions/json/.

Usage:
    ./manage.py import_decisions                       # import all councils found in ./data
    ./manage.py import_decisions AGY SWA                # just these councils
    ./manage.py import_decisions --after 2020-01-01     # only files dated on/after this
    ./manage.py import_decisions --before 2020-12-31    # only files dated on/before this
"""

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from core.models import Decision, Document
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from pypdf import PdfReader

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# settings.BASE_DIR is the lgsf_web package dir; data/ lives alongside manage.py, one level up
DATA_DIR = Path(settings.BASE_DIR).parent / "data"


logger = logging.getLogger(__name__)


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).date()


def validate_date_arg(value):
    try:
        datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        raise CommandError(
            f"Invalid date {value!r}, expected YYYY-MM-DD"
        ) from None
    return value


def clean_text(text):
    # drop NUL/control bytes Postgres rejects, and lone surrogates pypdf sometimes emits
    text = text.encode("utf-8", "surrogatepass").decode("utf-8", "ignore")
    return _CONTROL_CHARS_RE.sub("", text)


def get_document_text(doc, council):
    if doc["content_type"] != "application/pdf":
        # TODO: handle other document types
        return ""

    path = DATA_DIR / council / "Decisions" / "documents" / doc["storage_key"]
    logger.info(path)

    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return clean_text(text)


VERBOSITY_TO_LOG_LEVEL = {
    0: logging.ERROR,
    1: logging.WARNING,
    2: logging.INFO,
    3: logging.DEBUG,
}


class Command(BaseCommand):
    help = "Import scraped decisions and documents from ./data/<COUNCIL>/Decisions/json/"

    def add_arguments(self, parser):
        parser.add_argument(
            "councils",
            nargs="*",
            help="Council codes to import. Defaults to all councils found in ./data.",
        )
        parser.add_argument(
            "--after",
            help="Only import files dated on or after this date (YYYY-MM-DD), based on the filename.",
        )
        parser.add_argument(
            "--before",
            help="Only import files dated on or before this date (YYYY-MM-DD), based on the filename.",
        )

    def handle(self, *args, **options):
        logging.basicConfig(
            level=VERBOSITY_TO_LOG_LEVEL.get(options["verbosity"], logging.INFO)
        )
        after = (
            validate_date_arg(options["after"]) if options["after"] else None
        )
        before = (
            validate_date_arg(options["before"]) if options["before"] else None
        )
        councils = [
            c.upper() for c in options["councils"]
        ] or self.discover_councils()
        if not councils:
            raise CommandError(f"No council data found in {DATA_DIR}")

        total_decisions = total_documents = 0
        for council in councils:
            json_dir = DATA_DIR / council / "Decisions" / "json"
            if not json_dir.is_dir():
                self.stderr.write(f"Skipping {council}: no data at {json_dir}")
                continue

            files = self.filter_files(json_dir, after, before)
            self.stdout.write(f"{council}: importing {len(files)} decisions")
            for file_path in files:
                documents_imported = self.import_file(council, file_path)
                total_decisions += 1
                total_documents += documents_imported

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {total_decisions} decisions and {total_documents} documents"
            )
        )

    @staticmethod
    def discover_councils():
        return sorted(
            p.name
            for p in DATA_DIR.iterdir()
            if p.is_dir() and (p / "Decisions" / "json").is_dir()
        )

    @staticmethod
    def filter_files(json_dir, after, before):
        files = []
        for file_path in json_dir.glob("*.json"):
            file_date = file_path.name[:10]
            if after and file_date < after:
                continue
            if before and file_date > before:
                continue
            files.append(file_path)
        return sorted(files)

    @transaction.atomic
    def import_file(self, council, file_path):
        logger.info(file_path)
        data = json.loads(file_path.read_text())
        source = data["source"]

        decision, _ = Decision.objects.update_or_create(
            council=council,
            raw_identifier=data["raw_identifier"],
            defaults={
                "raw_title": data["raw_title"] or "",
                "raw_date": parse_date(data["raw_date"]),
                "raw_decision_maker": data["raw_decision_maker"] or "",
                "publication_date": parse_date(data["publication_date"]),
                "purpose": data["purpose"] or "",
                "status": data["status"] or "",
                "text": data["text"] or "",
                "url": data["url"],
                "is_key_decision": data["is_key_decision"],
                "is_officer_decision": data["is_officer_decision"],
                "is_subject_to_call_in": data["is_subject_to_call_in"],
                "source_url": source["url"],
                "source_etag": source["etag"],
                "source_last_modified": source["last_modified"],
            },
        )

        # re-import documents fresh each time, rather than trying to diff/upsert them
        # TODO: update_or_create on storage_key?
        decision.documents.all().delete()
        documents = [
            Document(
                decision=decision,
                attachment_id=doc["attachment_id"] or "",
                title=doc["title"],
                url=doc["url"],
                content_type=doc["content_type"] or "",
                content_length=doc["content_length"],
                content_hash=doc["content_hash"],
                etag=doc["etag"] or "",
                last_modified=doc["last_modified"],
                storage_backend=doc["storage_backend"],
                storage_key=doc["storage_key"],
                text=get_document_text(doc, council),
            )
            for doc in data["documents"]
            ###
            # workaround for bug in scrapers
            # TODO: scrapers should not make a Document object
            # if error from upstream API
            if "storage_key" in doc
            ###
            # ignore legacy document format for now
            # TODO: deal with this somehow
            and "content_type" in doc
            and "etag" in doc
        ]
        Document.objects.bulk_create(documents)
        return len(documents)
