"""
Recreate the OpenSearch index and load every Chunk and Decision into it.

Usage:
    ./manage.py load_opensearch

Set LIMIT below to load only some chunks and decisions while testing.

The index holds two kinds of object, told apart by `object_type`:

- "chunk": `_id` is "chunk-<Chunk pk>". Carries `document_id` and
  `decision_id`, so a hit can be turned back into a Chunk, Document and
  Decision with one query:

      chunks = Chunk.objects.select_related("document__decision").in_bulk(ids)

- "decision": `_id` is "decision-<Decision pk>". Has `decision_id` only,
  no document, and no embedding.
"""

from itertools import chain

from core.models import Chunk, Decision
from core.opensearch import (
    CHUNK,
    DECISION,
    INDEX_NAME,
    SEARCH_PIPELINE,
    opensearch_client,
)
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.management.base import BaseCommand, CommandError
from opensearchpy import helpers

#: Only load this many chunks and this many decisions. None loads all.
LIMIT = None


BULK_SIZE = 500
EMBEDDING_DIMENSIONS = 1024

# Weights are for the queries in order: full text, then vector.
SEARCH_PIPELINE_BODY = {
    "description": "Normalise and combine full text and vector scores",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {
                    "technique": "arithmetic_mean",
                    # 70% keyword match, 30% semantic similarity
                    "parameters": {"weights": [0.7, 0.3]},
                },
            }
        }
    ],
}

INDEX_BODY = {
    "settings": {
        "index": {
            "knn": True,
            # Must cover max_gram - min_gram of the ngram filter/tokenizer.
            "max_ngram_diff": 12,
        },
        "analysis": {
            "analyzer": {
                # The built-in english analyzer plus accent folding, so
                # "Cafe" matches "Café". Fuzziness is a query-time option
                # (`"fuzziness": "AUTO"` on a match query).
                "english_folded": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": [
                        "english_possessive_stemmer",
                        "lowercase",
                        "asciifolding",
                        "english_stop",
                        "english_stemmer",
                    ],
                },
                # Same analyzers as django-modelsearch.
                "ngram_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["asciifolding", "lowercase", "ngram"],
                },
                "edgengram_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["asciifolding", "lowercase", "edgengram"],
                },
            },
            "tokenizer": {
                "ngram_tokenizer": {
                    "type": "ngram",
                    "min_gram": 3,
                    "max_gram": 15,
                },
                "edgengram_tokenizer": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 15,
                    "side": "front",
                },
            },
            "filter": {
                "english_possessive_stemmer": {
                    "type": "stemmer",
                    "language": "possessive_english",
                },
                "english_stop": {"type": "stop", "stopwords": "_english_"},
                "english_stemmer": {"type": "stemmer", "language": "english"},
                "ngram": {"type": "ngram", "min_gram": 3, "max_gram": 15},
                "edgengram": {
                    "type": "edge_ngram",
                    "min_gram": 1,
                    "max_gram": 15,
                },
            },
        },
    },
    "mappings": {
        "dynamic": "strict",
        # Vectors are big and only needed for searching.
        "_source": {"excludes": ["embedding"]},
        "properties": {
            # "chunk" or "decision". The _id is "<object_type>-<pk>".
            "object_type": {"type": "keyword"},
            # Link back to Postgres. document_id and chunk_id
            # are only set on chunks.
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "integer"},
            "decision_id": {"type": "integer"},
            # Full text. raw_title is only set on decisions.
            "raw_title": {"type": "text", "analyzer": "english_folded"},
            "text": {"type": "text", "analyzer": "english_folded"},
            # Vector
            "embedding": {
                "type": "knn_vector",
                "dimension": EMBEDDING_DIMENSIONS,
                "method": {
                    "name": "hnsw",
                    # "engine": "lucene",
                    "space_type": "cosinesimil",
                    "parameters": {"m": 16, "ef_construction": 64},
                },
            },
            # Decision filters
            "council": {"type": "keyword"},
            "status": {"type": "keyword"},
            "is_key_decision": {"type": "boolean"},
            "is_officer_decision": {"type": "boolean"},
            "is_subject_to_call_in": {"type": "boolean"},
            "publication_date": {"type": "date", "format": "yyyy-MM-dd"},
        },
    },
}


def decision_filters(decision):
    return {
        "council": decision.council_id,
        "status": decision.status,
        "is_key_decision": decision.is_key_decision,
        "is_officer_decision": decision.is_officer_decision,
        "is_subject_to_call_in": decision.is_subject_to_call_in,
        "publication_date": (
            decision.publication_date.isoformat()
            if decision.publication_date
            else None
        ),
    }


def decision_to_action(decision):
    source = {
        "object_type": DECISION,
        "decision_id": decision.pk,
        "raw_title": decision.raw_title,
        "text": decision.text,
        **decision_filters(decision),
    }
    return {
        "_index": INDEX_NAME,
        "_id": f"{DECISION}-{decision.pk}",
        "_source": source,
    }


def chunk_to_action(chunk):
    document = chunk.document
    decision = document.decision
    try:
        embedding = chunk.embedding.embedding
    except ObjectDoesNotExist:
        # Chunks with embed=False have no vector. They can still be
        # found by full text search.
        embedding = None

    source = {
        "object_type": CHUNK,
        "chunk_id": chunk.chunk_id,
        "document_id": document.pk,
        "decision_id": decision.pk,
        "text": chunk.text,
        **decision_filters(decision),
    }
    if embedding is not None:
        source["embedding"] = embedding
    return {
        "_index": INDEX_NAME,
        "_id": f"{CHUNK}-{chunk.pk}",
        "_source": source,
    }


class Command(BaseCommand):
    help = "Recreate the OpenSearch index and load Chunks and Decisions into it"

    def handle(self, *args, **options):
        client = opensearch_client()
        try:
            client.cat.indices()
        except Exception as e:
            raise CommandError(
                f"Can't reach OpenSearch at {settings.OPENSEARCH_URL}: {e}"
            ) from e

        if client.indices.exists(index=INDEX_NAME):
            client.indices.delete(index=INDEX_NAME)
            self.stdout.write(f"Deleted index {INDEX_NAME}")

        client.transport.perform_request(
            "PUT",
            f"/_search/pipeline/{SEARCH_PIPELINE}",
            body=SEARCH_PIPELINE_BODY,
        )
        client.indices.create(index=INDEX_NAME, body=INDEX_BODY)
        self.stdout.write(f"Created index {INDEX_NAME}")

        chunks = Chunk.objects.select_related(
            "document__decision", "embedding"
        ).order_by("pk")
        decisions = Decision.objects.order_by("pk")
        if LIMIT is not None:
            chunks = chunks[:LIMIT]
            decisions = decisions[:LIMIT]

        indexed = failed = 0
        actions = chain(
            (decision_to_action(d) for d in decisions.iterator(BULK_SIZE)),
            (chunk_to_action(c) for c in chunks.iterator(BULK_SIZE)),
        )
        for ok, result in helpers.streaming_bulk(
            client,
            actions,
            chunk_size=BULK_SIZE,
            raise_on_error=False,
            raise_on_exception=False,
        ):
            if ok:
                indexed += 1
            else:
                failed += 1
                self.stderr.write(str(result))
            if (indexed + failed) % BULK_SIZE == 0:
                self.stdout.write(f"{indexed + failed} objects sent")

        client.indices.refresh(index=INDEX_NAME)
        self.stdout.write(
            self.style.SUCCESS(f"Indexed {indexed} objects, {failed} failed")
        )
