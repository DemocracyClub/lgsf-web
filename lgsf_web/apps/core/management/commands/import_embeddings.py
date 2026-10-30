"""
Import chunks and embeddings from ./data/<COUNCIL>/Decisions/documents/.

For each <filename>.pdf, looks for:
- <filename>.pdf.chunks.jsonl     -> Chunk objects
- <filename>.pdf.titan-v2.jsonl   -> Embedding objects for those chunks

Chunks are matched to a Document by Document.content_hash == chunk.metadata.content_hash.
Existing chunks (and their embeddings) for a matched document are replaced.
Every DecisionEmbedding is then remade, with compute_decision_embeddings.

Usage:
    ./manage.py import_embeddings                # all councils found in ./data
    ./manage.py import_embeddings AGY SWA        # just these councils
"""

import json
import logging

from core.management.helpers import (
    DATA_DIR,
    VERBOSITY_TO_LOG_LEVEL,
    clean_text,
    parse_date,
)
from core.models import Chunk, Document, Embedding
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)


def read_jsonl(path):
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


class Command(BaseCommand):
    help = "Import chunks and embeddings from ./data/<COUNCIL>/Decisions/documents/"

    def add_arguments(self, parser):
        parser.add_argument(
            "councils",
            nargs="*",
            help="Council codes to import. Defaults to all councils found in ./data.",
        )

    def handle(self, *args, **options):
        logging.basicConfig(
            level=VERBOSITY_TO_LOG_LEVEL.get(options["verbosity"], logging.INFO)
        )
        councils = [
            c.upper() for c in options["councils"]
        ] or self.discover_councils()
        if not councils:
            raise CommandError(f"No council data found in {DATA_DIR}")

        total_chunks = total_embeddings = 0
        for council in councils:
            documents_dir = DATA_DIR / council / "Decisions" / "documents"
            if not documents_dir.is_dir():
                self.stderr.write(
                    f"Skipping {council}: no data at {documents_dir}"
                )
                continue

            files = sorted(documents_dir.glob("*.pdf"))
            self.stdout.write(f"{council}: checking {len(files)} documents")
            for pdf_path in files:
                chunks_path = pdf_path.with_name(
                    pdf_path.name + ".chunks.jsonl"
                )
                titan_path = pdf_path.with_name(
                    pdf_path.name + ".titan-v2.jsonl"
                )
                if not chunks_path.is_file():
                    continue

                chunks_imported, embeddings_imported = self.import_file(
                    chunks_path, titan_path if titan_path.is_file() else None
                )
                total_chunks += chunks_imported
                total_embeddings += embeddings_imported

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {total_chunks} chunks and {total_embeddings} embeddings"
            )
        )
        call_command("compute_decision_embeddings", stdout=self.stdout)

    @staticmethod
    def discover_councils():
        return sorted(
            p.name
            for p in DATA_DIR.iterdir()
            if p.is_dir() and (p / "Decisions" / "documents").is_dir()
        )

    @staticmethod
    def find_document(content_hash, cache):
        if content_hash not in cache:
            matches = list(
                Document.objects.filter(content_hash=content_hash)[:2]
            )
            if len(matches) != 1:
                logger.warning(
                    "content_hash %s matched %s documents; skipping",
                    content_hash,
                    "0" if not matches else ">1",
                )
            cache[content_hash] = matches[0] if len(matches) == 1 else None
        return cache[content_hash]

    @transaction.atomic
    def import_file(self, chunks_path, titan_path):
        logger.info(chunks_path)

        documents = {}
        chunks_to_create = []
        for data in read_jsonl(chunks_path):
            document = self.find_document(
                data["metadata"]["content_hash"], documents
            )
            if document is None:
                continue

            chunks_to_create.append(
                Chunk(
                    document=document,
                    chunk_id=data["chunk_id"],
                    parent_id=data["parent_id"],
                    chunk_index=data["chunk_index"],
                    chunk_count=data["chunk_count"],
                    context=clean_text(data["context"]),
                    text=clean_text(data["text"]),
                    text_hash=data["text_hash"],
                    word_count=data["word_count"],
                    date=parse_date(data["date"]),
                    embed=data["embed"],
                    source_type=data["source_type"],
                    type=data["type"],
                    metadata=data["metadata"],
                )
            )

        matched_documents = [d for d in documents.values() if d is not None]
        # cascades to Embedding
        Chunk.objects.filter(document__in=matched_documents).delete()
        chunks = Chunk.objects.bulk_create(chunks_to_create)

        if titan_path is None:
            return len(chunks), 0

        chunks_by_id = {c.chunk_id: c for c in chunks}
        embeddings_to_create = []
        for data in read_jsonl(titan_path):
            chunk = chunks_by_id.get(data["chunk_id"])
            if chunk is None:
                logger.warning(
                    "No chunk found for embedding %s; skipping",
                    data["chunk_id"],
                )
                continue

            embeddings_to_create.append(
                Embedding(
                    chunk=chunk,
                    model=data["model"],
                    token_count=data["token_count"],
                    embedding=data["embedding"],
                )
            )

        embeddings = Embedding.objects.bulk_create(embeddings_to_create)
        return len(chunks), len(embeddings)
