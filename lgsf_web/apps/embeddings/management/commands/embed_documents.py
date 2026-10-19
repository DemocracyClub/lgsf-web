"""
Convert decisions' documents with Docling, split them into chunks and
embed the chunks with Titan v2, writing the results next to each
document as sidecar files. See sidecars.py for the files, and the rules
for when each stage runs again.

Usage:
    ./manage.py embed_documents MAN --since 2026-01-01 --dry-run
    ./manage.py embed_documents MAN --since 2026-01-01
    ./manage.py embed_documents MAN --stages extract,chunk     # no AWS needed
    ./manage.py embed_documents --source s3 --limit 3

Embedding needs AWS credentials with bedrock:InvokeModel, for example
AWS_PROFILE=dev-lgsf-dc. Extracting and chunking need the embeddings
dependency group: uv sync --group embeddings.
"""

import argparse
import collections
import datetime

from core.models import Document
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from embeddings.embedders import EMBEDDERS
from embeddings.extract import Device
from embeddings.formats import detect_format
from embeddings.sidecars import Stage, list_keys, plan_task, read_statuses
from embeddings.stores import LocalStore, S3Store, Source
from embeddings.tasks import build_tasks, read_manifest


def parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}, expected YYYY-MM-DD"
        ) from None


def parse_stages(value):
    try:
        return [Stage(stage.strip()) for stage in value.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid stages {value!r}, expected a comma-separated list "
            f"of {', '.join(Stage)}"
        ) from None


class Command(BaseCommand):
    help = (
        "Convert, chunk and embed decisions' documents, writing the "
        "results next to each document"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "councils",
            nargs="*",
            help="Council codes. Defaults to every council in the database.",
        )
        parser.add_argument(
            "--since",
            type=parse_date,
            help="Only documents linked from decisions on or after this "
            "date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--until",
            type=parse_date,
            help="Only documents linked from decisions on or before this "
            "date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--document",
            type=int,
            action="append",
            dest="documents",
            metavar="ID",
            help="Only this Document. Can be given more than once.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Only the first this many files",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            help="Leave out PDFs with more pages than this, for a later run",
        )
        parser.add_argument(
            "--stages",
            type=parse_stages,
            default=list(Stage),
            help=f"Which stages to run (default {','.join(Stage)})",
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Extract again files that failed or timed out before",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run every stage again, even for files already done",
        )
        parser.add_argument(
            "--source",
            choices=list(Source),
            default=Source.LOCAL,
            type=Source,
            help="Where the documents are: LGSF_DATA_DIR (local, the "
            "default) or the data/ prefix of LGSF_DATA_BUCKET (s3)",
        )
        parser.add_argument(
            "--device",
            choices=list(Device),
            default=Device.AUTO,
            type=Device,
            help="What Docling runs its models on (default auto)",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=4,
            help="How many files to convert at once, each in its own "
            "process with its own copy of Docling's models (default 4)",
        )
        parser.add_argument(
            "--threads",
            type=int,
            default=4,
            help="How many threads each worker uses (default 4)",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=1800,
            help="Give up on a file after this many seconds (default 1800)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Say what would be done, without doing it",
        )
        parser.add_argument(
            "--manifest",
            metavar="PATH",
            help="Run the tasks in a manifest directory, or s3:// URL, "
            "instead of finding them in the database",
        )

    def handle(self, *args, **options):
        self.options = options
        tasks = self.get_tasks()
        store = self.get_store()

        existing = list_keys(store, tasks)
        statuses = read_statuses(store, tasks, existing)
        plans = [
            plan_task(
                task,
                {
                    key: statuses[(task.council, key)]
                    for key in task.storage_keys
                },
                options["stages"],
                list(EMBEDDERS),
                retry_failed=options["retry_failed"],
                force=options["force"],
            )
            for task in tasks
        ]
        if options["dry_run"]:
            self.output_plan(plans, store, existing)
            return
        raise CommandError("Only --dry-run is implemented so far")

    def get_tasks(self):
        options = self.options
        if options["manifest"]:
            return read_manifest(options["manifest"])

        documents = Document.objects.all()
        if options["councils"]:
            councils = [council.upper() for council in options["councils"]]
            documents = documents.filter(decision__council__in=councils)
        if options["since"]:
            documents = documents.filter(
                decision__raw_date__gte=options["since"]
            )
        if options["until"]:
            documents = documents.filter(
                decision__raw_date__lte=options["until"]
            )
        if options["documents"]:
            documents = documents.filter(id__in=options["documents"])
        return build_tasks(documents, limit=options["limit"])

    def get_store(self):
        if self.options["source"] == Source.S3:
            return S3Store(settings.LGSF_DATA_BUCKET)
        return LocalStore(settings.LGSF_DATA_DIR)

    def output_plan(self, plans, store, existing):
        """
        What a run would do, with the formats of the files to work on:
        from their status if they have one, or from the file itself if
        it's local.
        """
        documents = sum(len(plan.task.documents) for plan in plans)
        size = sum(plan.task.content_length for plan in plans)
        self.stdout.write(
            f"{documents} documents, in {len(plans)} files of "
            f"{size / 1e6:.1f}MB in all, in {store!r}"
        )

        formats = collections.Counter()
        statuses = collections.Counter()
        needs = collections.Counter()
        for plan in plans:
            task = plan.task
            primary_key = task.document_key(task.primary.storage_key)
            if plan.status and plan.status.format:
                formats[str(plan.status.format)] += 1
            elif primary_key not in existing:
                formats["missing"] += 1
            elif isinstance(store, LocalStore):
                formats[str(detect_format(store.path(primary_key)))] += 1
            else:
                formats["not downloaded"] += 1

            if plan.status and plan.status.extract:
                statuses[str(plan.status.extract.status)] += 1
            else:
                statuses["not extracted"] += 1

            if plan.extract:
                needs["extract"] += 1
            elif plan.chunk:
                needs["chunk"] += 1
            elif plan.embed:
                needs["embed"] += 1
            elif plan.nothing_to_do():
                needs["nothing"] += 1
            else:
                needs["copy"] += 1

        self.output_counts("Formats", formats)
        self.output_counts("Extraction status", statuses)
        self.output_counts(
            "To do (the first stage each file needs)",
            needs,
            order=["extract", "chunk", "embed", "copy", "nothing"],
        )

    def output_counts(self, title, counts, order=None):
        self.stdout.write(f"\n{title}:")
        names = order or [name for name, _ in counts.most_common()]
        for name in names:
            if counts[name]:
                self.stdout.write(f"  {counts[name]:>7}  {name}")
