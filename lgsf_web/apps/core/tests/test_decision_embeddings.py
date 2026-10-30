import datetime

import numpy
import pytest
from core.models import Chunk, Decision, DecisionEmbedding, Document, Embedding
from core.views import TITAN_MODEL
from django.core.management import call_command


def vector(**components):
    """A 1024-dimension vector, zero but for e.g. `x0=1, x5=0.5`."""
    v = numpy.zeros(1024)
    for name, value in components.items():
        v[int(name[1:])] = value
    return v


def make_decision(council_id, identifier):
    return Decision.objects.create(
        council_id=council_id,
        raw_identifier=identifier,
        raw_title=f"Decision {identifier}",
        url=f"https://example.com/{identifier}",
    )


def add_chunks(decision, *vectors):
    document = Document.objects.create(
        decision=decision,
        url=f"https://example.com/{decision.raw_identifier}.pdf",
        storage_key=f"{decision.raw_identifier}.pdf",
    )
    for index, v in enumerate(vectors):
        chunk = Chunk.objects.create(
            document=document,
            chunk_id=f"{decision.raw_identifier}-{index}",
            parent_id=decision.raw_identifier,
            chunk_index=index,
            chunk_count=len(vectors),
            context="",
            text="",
            text_hash="",
            word_count=0,
            date=datetime.date(2026, 1, 1),
            embed=True,
            source_type="pdf",
            type="text",
            metadata={},
        )
        Embedding.objects.create(
            chunk=chunk, model=TITAN_MODEL, token_count=0, embedding=v
        )


@pytest.mark.django_db
def test_compute_takes_council_mean_from_decision_means():
    first = make_decision("MAN", "1")
    second = make_decision("MAN", "2")
    add_chunks(first, vector(x0=1), vector(x1=1))
    add_chunks(second, vector(x2=1))

    call_command("compute_decision_embeddings")

    # first's mean is (0.5, 0.5, 0), second's (0, 0, 1), and the
    # council's (0.25, 0.25, 0.5)
    numpy.testing.assert_allclose(
        DecisionEmbedding.objects.get(decision=first).embedding,
        vector(x0=0.25, x1=0.25, x2=-0.5),
    )
    numpy.testing.assert_allclose(
        DecisionEmbedding.objects.get(decision=second).embedding,
        vector(x0=-0.25, x1=-0.25, x2=0.5),
    )


@pytest.mark.django_db
def test_compute_leaves_out_council_with_one_decision():
    add_chunks(make_decision("MAN", "1"), vector(x0=1))
    add_chunks(make_decision("MAN", "2"), vector(x1=1))
    add_chunks(make_decision("SLF", "3"), vector(x2=1))

    call_command("compute_decision_embeddings")

    assert set(
        DecisionEmbedding.objects.values_list(
            "decision__raw_identifier", flat=True
        )
    ) == {"1", "2"}


@pytest.mark.django_db
def test_compute_replaces_existing_embeddings():
    first = make_decision("MAN", "1")
    add_chunks(first, vector(x0=1))
    add_chunks(make_decision("MAN", "2"), vector(x1=1))
    call_command("compute_decision_embeddings")
    first.delete()
    add_chunks(make_decision("MAN", "3"), vector(x2=1))

    call_command("compute_decision_embeddings")

    assert set(
        DecisionEmbedding.objects.values_list(
            "decision__raw_identifier", flat=True
        )
    ) == {"2", "3"}
