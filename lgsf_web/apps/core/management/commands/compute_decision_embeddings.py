"""
Remake every DecisionEmbedding from the chunk embeddings.

A decision's embedding is the mean of its chunks' embeddings, less the
mean of those for every decision of its council. Since a council's mean
depends on all its decisions, they are all remade together.

Usage:
    ./manage.py compute_decision_embeddings
"""

from core.models import DecisionEmbedding
from core.views import TITAN_MODEL
from django.core.management.base import BaseCommand
from django.db import connection, transaction

# A council with one decision is left out: taking away its mean would
# leave a zero vector, which has no cosine distance to anything.
INSERT_DECISION_EMBEDDINGS = """
WITH decision_means AS (
    SELECT document.decision_id, AVG(embedding.embedding) AS embedding
    FROM core_embedding embedding
    JOIN core_chunk chunk ON chunk.id = embedding.chunk_id
    JOIN core_document document ON document.id = chunk.document_id
    WHERE embedding.model = %(model)s
    GROUP BY document.decision_id
),
council_means AS (
    SELECT decision.council_id, AVG(decision_means.embedding) AS embedding
    FROM decision_means
    JOIN core_decision decision ON decision.id = decision_means.decision_id
    GROUP BY decision.council_id
    HAVING COUNT(*) > 1
)
INSERT INTO core_decisionembedding (decision_id, model, embedding)
SELECT
    decision_means.decision_id,
    %(model)s,
    decision_means.embedding - council_means.embedding
FROM decision_means
JOIN core_decision decision ON decision.id = decision_means.decision_id
JOIN council_means ON council_means.council_id = decision.council_id
"""


class Command(BaseCommand):
    help = "Remake every DecisionEmbedding from the chunk embeddings"

    @transaction.atomic
    def handle(self, *args, **options):
        DecisionEmbedding.objects.all().delete()
        with connection.cursor() as cursor:
            cursor.execute(INSERT_DECISION_EMBEDDINGS, {"model": TITAN_MODEL})
            count = cursor.rowcount
        self.stdout.write(
            self.style.SUCCESS(f"Made {count} decision embeddings")
        )
