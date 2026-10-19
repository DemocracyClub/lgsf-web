"""
The chunk and embedding records, and deciding which chunks need
embedding.

from_dict() is what the embedding step reads the JSONL with, so it must
reverse as_dict() exactly. A fake embedder is used, so nothing here
needs a model or the network.
"""

import json

import pytest
from embeddings.records import (
    Chunk,
    ChunkType,
    EmbeddingRecord,
    SourceType,
    embed_chunks,
)

from .fakes import FakeEmbedder


def make_chunk(index=0, **kwargs):
    fields = {
        "chunk_id": f"MAN:documents:98e2:{index}",
        "parent_id": "MAN:documents:98e2",
        "council": "MAN",
        "type": ChunkType.DOCUMENTS,
        "source_type": SourceType.PDF_DOCLING,
        "date": "2026-08-06",
        "context": "Manchester City Council · City Treasurer · 6 August 2026",
        "text": f"The City Treasurer approved report {index}.",
        "chunk_index": index,
        "chunk_count": 3,
        "embed": True,
        "metadata": {"pages": [1], "headings": ["Notice of Decision Made"]},
    }
    fields.update(kwargs)
    return Chunk(**fields)


@pytest.fixture
def chunks():
    return [make_chunk(0), make_chunk(1, embed=False), make_chunk(2)]


def as_existing(records):
    return {record.chunk_id: record for record in records}


# Chunk


def test_as_dict_from_dict_round_trip():
    chunk = make_chunk()
    assert Chunk.from_dict(chunk.as_dict()) == chunk


def test_round_trip_through_json():
    chunk = make_chunk()
    loaded = Chunk.from_dict(json.loads(chunk.as_json()))
    assert loaded == chunk
    assert loaded.type is ChunkType.DOCUMENTS


def test_as_dict_writes_enums_as_strings_and_derived_fields():
    data = json.loads(make_chunk().as_json())
    assert data["type"] == "documents"
    assert data["source_type"] == "pdf_docling"
    assert data["word_count"] == 6
    assert len(data["text_hash"]) == 64


def test_as_json_is_one_line():
    assert "\n" not in make_chunk(text="One.\n\nTwo.").as_json()


def test_embed_text_puts_context_before_text():
    chunk = make_chunk(context="Header", text="Body")
    assert chunk.embed_text == "Header\n\nBody"


def test_text_hash_changes_when_context_changes():
    assert make_chunk().text_hash != make_chunk(context="Cabinet").text_hash


def test_text_hash_ignores_fields_not_embedded():
    assert (
        make_chunk().text_hash
        == make_chunk(chunk_count=5, embed=False).text_hash
    )


# embed_chunks()


def test_embeds_chunks_with_embed_true_in_order(chunks):
    embedder = FakeEmbedder()
    records, embedded = embed_chunks(chunks, embedder, {})
    assert [r.chunk_id for r in records] == [
        "MAN:documents:98e2:0",
        "MAN:documents:98e2:2",
    ]
    assert embedded == 2
    assert embedder.texts == [chunks[0].embed_text, chunks[2].embed_text]


def test_record_fields(chunks):
    embedder = FakeEmbedder()
    record = embed_chunks(chunks, embedder, {})[0][0]
    assert record.text_hash == chunks[0].text_hash
    assert record.model == "fake-model-1"
    assert record.embedding == embedder.vector(chunks[0].embed_text)
    assert record.token_count == len(chunks[0].embed_text.split())


def test_unchanged_chunks_are_reused(chunks):
    first, _ = embed_chunks(chunks, FakeEmbedder(), {})
    embedder = FakeEmbedder()
    records, embedded = embed_chunks(chunks, embedder, as_existing(first))
    assert records == first
    assert embedded == 0
    assert embedder.texts == []


def test_changed_chunk_is_embedded_again(chunks):
    first, _ = embed_chunks(chunks, FakeEmbedder(), {})
    chunks[2] = make_chunk(2, text="The City Treasurer rejected the report.")
    embedder = FakeEmbedder()
    records, embedded = embed_chunks(chunks, embedder, as_existing(first))
    assert embedded == 1
    assert embedder.texts == [chunks[2].embed_text]
    assert records[0] == first[0]
    assert records[1].text_hash == chunks[2].text_hash


def test_other_models_records_are_not_reused(chunks):
    first, _ = embed_chunks(chunks, FakeEmbedder(), {})

    class OtherModel(FakeEmbedder):
        model = "fake-model-2"

    records, embedded = embed_chunks(chunks, OtherModel(), as_existing(first))
    assert embedded == 2
    assert {r.model for r in records} == {"fake-model-2"}


def test_records_of_another_size_are_not_reused(chunks):
    first, _ = embed_chunks(chunks, FakeEmbedder(), {})

    class Smaller(FakeEmbedder):
        dimensions = 2

    records, embedded = embed_chunks(chunks, Smaller(), as_existing(first))
    assert embedded == 2
    assert all(len(r.embedding) == 2 for r in records)


def test_records_for_chunks_that_have_gone_are_dropped(chunks):
    first, _ = embed_chunks(chunks, FakeEmbedder(), {})
    records, _ = embed_chunks(chunks[:2], FakeEmbedder(), as_existing(first))
    assert [r.chunk_id for r in records] == ["MAN:documents:98e2:0"]


def test_record_round_trip(chunks):
    record = embed_chunks(chunks, FakeEmbedder(), {})[0][0]
    assert EmbeddingRecord.from_dict(record.as_dict()) == record
