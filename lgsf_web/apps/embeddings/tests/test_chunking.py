"""
Chunks and their headers, and the hash that decides when a document is
chunked again.

The chunks of the MAN decision notice are compared with the expected
chunks in fixtures/MAN.
"""

import dataclasses
import json
from pathlib import Path

import pytest
from embeddings.chunking import inputs_hash
from embeddings.formats import DocumentFormat
from embeddings.records import SourceType

from .factories import man_document, man_task

FIXTURES = Path(__file__).parent / "fixtures" / "MAN"


@pytest.fixture(scope="module")
def docling_document():
    docling_core = pytest.importorskip("docling_core.types.doc")
    return docling_core.DoclingDocument.load_from_json(
        FIXTURES / "2026-08-06-1172-s65106.pdf.docling.json"
    )


def chunk(task, docling_document, document_format=DocumentFormat.PDF):
    from embeddings.chunking import chunk_document

    return chunk_document(task, docling_document, document_format)


def test_chunks_match_the_expected_chunks(docling_document):
    path = FIXTURES / "2026-08-06-1172-s65106.pdf.expected-chunks.jsonl"
    expected = [json.loads(line) for line in path.read_text().splitlines()]
    chunks = chunk(man_task(), docling_document)
    assert [c.as_dict() for c in chunks] == expected


def test_context_header(docling_document):
    chunks = chunk(man_task(), docling_document)
    assert chunks[1].context == (
        "Manchester City Council · Strategic Director (Corporate Services) "
        "& City Treasurer · 6 August 2026\n"
        "Decision: P-1475 Domestic Abuse - Intersecting Needs Safe "
        "Accommodation (2026/06/09A)\n"
        "D3 P-1475 Domestic Abuse - Intersecting Needs Safe Accommodation"
        " · Notice of Decision Made"
    )


def test_short_chunks_are_not_embedded(docling_document):
    chunks = chunk(man_task(), docling_document)
    assert [c.embed for c in chunks] == [False, True, True, True]


def test_meeting_date_is_left_out_of_the_decision_maker(docling_document):
    task = man_task(man_document(decision_maker="12/01/2026 - Cabinet"))
    chunks = chunk(task, docling_document)
    assert chunks[1].context.startswith(
        "Manchester City Council · Cabinet · 6 August 2026\n"
    )


def test_a_file_linked_from_several_decisions(docling_document):
    later = dataclasses.replace(
        man_document(
            id=1900,
            identifier="1200",
            title="Later",
            date="2026-09-01",
        ),
        id=4000,
        storage_key="2026-09-01-1200-s70000.pdf",
    )
    chunks = chunk(man_task(man_document(), later), docling_document)
    # The header and the top-level fields are the primary Document's, and
    # the metadata lists both decisions.
    assert chunks[1].date == "2026-08-06"
    assert "6 August 2026" in chunks[1].context
    assert chunks[1].metadata["storage_key"] == "2026-08-06-1172-s65106.pdf"
    assert [d["identifier"] for d in chunks[1].metadata["decisions"]] == [
        "1172",
        "1200",
    ]


def test_source_type_is_the_format_converted(docling_document):
    chunks = chunk(man_task(), docling_document, DocumentFormat.DOCX)
    assert {c.source_type for c in chunks} == {SourceType.DOCX_DOCLING}


# inputs_hash()


def man_hash(task=None, **kwargs):
    return inputs_hash(
        task or man_task(), DocumentFormat.PDF, "2.130.0", **kwargs
    )


def test_inputs_hash_is_stable():
    assert man_hash() == man_hash()
    assert man_hash().startswith("sha256:")


@pytest.mark.parametrize(
    "decision_fields",
    [
        {"title": "Retitled"},
        {"decision_maker": "Cabinet"},
        {"date": "2026-08-07"},
        {"url": "https://example.org/1172"},
    ],
)
def test_inputs_hash_changes_with_the_decision(decision_fields):
    assert man_hash(man_task(man_document(**decision_fields))) != man_hash()


def test_inputs_hash_changes_with_the_document():
    document = dataclasses.replace(man_document(), title="Retitled")
    assert man_hash(man_task(document)) != man_hash()


def test_inputs_hash_changes_with_another_linking_document():
    later = dataclasses.replace(
        man_document(id=1900, identifier="1200"),
        storage_key="2026-09-01-1200-s70000.pdf",
    )
    assert man_hash(man_task(man_document(), later)) != man_hash()


def test_inputs_hash_changes_with_the_settings_and_versions():
    assert man_hash(max_words=300) != man_hash()
    assert man_hash(min_embed_words=10) != man_hash()
    assert inputs_hash(man_task(), DocumentFormat.PDF, "2.131.0") != man_hash()
    assert inputs_hash(man_task(), DocumentFormat.DOCX, "2.130.0") != (
        man_hash()
    )


def test_inputs_hash_ignores_database_ids():
    document = dataclasses.replace(man_document(id=1), id=2)
    assert man_hash(man_task(document)) == man_hash()


def test_inputs_hash_changes_with_chunker_version(monkeypatch):
    before = man_hash()
    monkeypatch.setattr("embeddings.chunking.CHUNKER_VERSION", 999)
    assert man_hash() != before
