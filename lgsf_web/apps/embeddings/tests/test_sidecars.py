"""
status.json, and the rules for which stages a task needs, across the
storage keys a file is stored under.
"""

import dataclasses

import pytest
from embeddings.extract import ExtractStatus
from embeddings.formats import DocumentFormat
from embeddings.sidecars import (
    ChunkEntry,
    DocumentStatus,
    EmbedEntry,
    ExtractEntry,
    Sidecar,
    Stage,
    needs_chunk,
    needs_embed,
    needs_extract,
    plan_task,
    read_status,
    read_statuses,
    sidecar_key,
    write_status,
)
from embeddings.stores import LocalStore

from .factories import make_task

ALL_STAGES = list(Stage)
EMBEDDERS = ["titan-v2"]


def done_status(task, **changes):
    """The status of a task that's been through every stage."""
    status = DocumentStatus(
        content_hash=task.content_hash,
        storage_keys=task.storage_keys,
        format=DocumentFormat.PDF,
        extract=ExtractEntry(
            status=ExtractStatus.OK,
            pages=2,
            seconds=3.1,
            docling_version="2.130.0",
            device="cpu",
            finished_at="2026-10-19T12:00:00+00:00",
        ),
    )
    chunk_hash = status.chunk_inputs_hash(task)
    status.chunk = ChunkEntry(
        inputs_hash=chunk_hash, max_words=350, chunks=4, embeddable=3
    )
    status.embed = {
        "titan-v2": EmbedEntry(
            model="amazon.titan-embed-text-v2:0",
            chunk_inputs_hash=chunk_hash,
            embedded=3,
            tokens=1234,
        )
    }
    return dataclasses.replace(status, **changes)


def extracted(task, extract_status=ExtractStatus.OK):
    status = done_status(task, chunk=None, embed={})
    status.extract.status = extract_status
    return status


@pytest.fixture
def task():
    return make_task(keys=("1-s1.pdf",))


# status.json


def test_status_round_trip(task):
    status = done_status(task)
    loaded = DocumentStatus.from_json(status.as_json())
    assert loaded == status
    assert loaded.extract.status is ExtractStatus.OK
    assert loaded.format is DocumentFormat.PDF


def test_status_of_a_left_out_file_round_trip(task):
    status = DocumentStatus(
        content_hash=task.content_hash,
        storage_keys=task.storage_keys,
        format=DocumentFormat.RESTRICTED,
        extract=ExtractEntry(status=ExtractStatus.RESTRICTED),
    )
    assert DocumentStatus.from_json(status.as_json()) == status


def test_read_and_write_status(tmp_path, task):
    store = LocalStore(tmp_path)
    key = task.document_key("1-s1.pdf")
    assert read_status(store, key) is None
    write_status(store, key, done_status(task))
    assert read_status(store, key) == done_status(task)
    assert store.exists(f"{key}.status.json")


def test_unreadable_status_is_missing(tmp_path, task):
    store = LocalStore(tmp_path)
    key = task.document_key("1-s1.pdf")
    store.write_bytes(sidecar_key(key, Sidecar.STATUS), b'{"content_')
    assert read_status(store, key) is None
    store.write_bytes(sidecar_key(key, Sidecar.STATUS), b'{"format": "x"}')
    assert read_status(store, key) is None


def test_read_statuses(tmp_path):
    store = LocalStore(tmp_path)
    task = make_task(keys=("1-s1.pdf", "2-s2.pdf", "3-s3.pdf"))
    write_status(store, task.document_key("1-s1.pdf"), done_status(task))
    # For a file the council has since replaced
    write_status(
        store,
        task.document_key("2-s2.pdf"),
        done_status(task, content_hash="sha256:old"),
    )
    assert read_statuses(store, [task]) == {
        ("TST", "1-s1.pdf"): done_status(task),
        ("TST", "2-s2.pdf"): None,
        ("TST", "3-s3.pdf"): None,
    }


def test_sidecars(task):
    assert done_status(task).sidecars() == [
        "docling.json",
        "md",
        "chunks.jsonl",
        "titan-v2.jsonl",
    ]
    status = done_status(task)
    status.embed["titan-v2"].error = "ThrottlingException"
    assert status.sidecars() == ["docling.json", "md", "chunks.jsonl"]
    assert extracted(task, ExtractStatus.FAILED).sidecars() == []


# Extract


def test_extract_without_a_status():
    assert needs_extract(None)


@pytest.mark.parametrize(
    "extract_status",
    [
        ExtractStatus.OK,
        ExtractStatus.PARTIAL,
        ExtractStatus.RESTRICTED,
        ExtractStatus.NOT_DOCUMENT,
        ExtractStatus.EMPTY,
        ExtractStatus.UNSUPPORTED,
    ],
)
def test_extract_is_not_repeated(task, extract_status):
    status = extracted(task, extract_status)
    assert not needs_extract(status)
    assert not needs_extract(status, retry_failed=True)
    assert needs_extract(status, force=True)


@pytest.mark.parametrize(
    "extract_status", [ExtractStatus.FAILED, ExtractStatus.TIMEOUT]
)
def test_failures_are_only_retried_when_asked(task, extract_status):
    status = extracted(task, extract_status)
    assert not needs_extract(status)
    assert needs_extract(status, retry_failed=True)


# Chunk


def test_chunk_after_extracting(task):
    status = extracted(task)
    assert needs_chunk(status, status.chunk_inputs_hash(task))


def test_chunk_is_not_repeated(task):
    status = done_status(task)
    assert not needs_chunk(status, status.chunk_inputs_hash(task))
    assert needs_chunk(status, status.chunk_inputs_hash(task), force=True)


def test_chunk_again_when_the_inputs_change(task):
    status = done_status(task)
    assert needs_chunk(status, "sha256:other")


def test_chunk_again_after_an_error(task):
    status = done_status(task)
    status.chunk = ChunkEntry(inputs_hash=None, max_words=350, error="Bad")
    assert needs_chunk(status, done_status(task).chunk.inputs_hash)


@pytest.mark.parametrize(
    "extract_status", [ExtractStatus.FAILED, ExtractStatus.RESTRICTED]
)
def test_nothing_to_chunk(task, extract_status):
    assert not needs_chunk(None, None)
    assert not needs_chunk(extracted(task, extract_status), None)


# Embed


def test_embed_after_chunking(task):
    status = done_status(task, embed={})
    assert needs_embed(status, "titan-v2")


def test_embed_is_not_repeated(task):
    status = done_status(task)
    assert not needs_embed(status, "titan-v2")
    assert needs_embed(status, "titan-v2", force=True)


def test_embed_with_another_model(task):
    assert needs_embed(done_status(task), "other-model")


def test_embed_again_after_an_error(task):
    status = done_status(task)
    status.embed["titan-v2"].error = "ThrottlingException"
    assert needs_embed(status, "titan-v2")


def test_embed_again_when_the_chunks_change(task):
    status = done_status(task)
    status.chunk.inputs_hash = "sha256:other"
    assert needs_embed(status, "titan-v2")


def test_nothing_to_embed(task):
    assert not needs_embed(None, "titan-v2")
    assert not needs_embed(extracted(task), "titan-v2")
    status = done_status(task)
    status.chunk.error = "Bad"
    assert not needs_embed(status, "titan-v2")


# Planning a task across its storage keys


def plan(task, statuses, stages=ALL_STAGES, **kwargs):
    return plan_task(task, statuses, stages, EMBEDDERS, **kwargs)


def test_plan_a_new_file(task):
    result = plan(task, {"1-s1.pdf": None})
    assert result.extract
    assert result.needs_worker
    assert result.copy_from is None


def test_plan_a_file_that_is_done(task):
    status = done_status(task)
    result = plan(task, {"1-s1.pdf": status})
    assert not result.needs_worker
    assert result.embed == []
    assert result.nothing_to_do()


def test_plan_a_retitled_decision(task):
    status = done_status(task)
    retitled = dataclasses.replace(
        task.documents[0],
        decision=dataclasses.replace(task.documents[0].decision, title="New"),
    )
    task.documents[0] = retitled
    result = plan(task, {"1-s1.pdf": status})
    assert not result.extract
    assert result.chunk


def test_plan_only_the_stages_asked_for(task):
    assert not plan(task, {"1-s1.pdf": None}, [Stage.CHUNK]).needs_worker
    status = extracted(task)
    result = plan(task, {"1-s1.pdf": status}, [Stage.EXTRACT, Stage.EMBED])
    assert not result.needs_worker
    assert result.embed == []
    assert plan(task, {"1-s1.pdf": status}, [Stage.CHUNK]).chunk


def test_plan_embedding_alone(task):
    result = plan(task, {"1-s1.pdf": done_status(task, embed={})})
    assert not result.needs_worker
    assert result.embed == ["titan-v2"]


def test_force(task):
    result = plan(task, {"1-s1.pdf": done_status(task)}, force=True)
    assert result.extract


def test_every_key_gets_the_primary_keys_status():
    task = make_task(keys=("1-s1.pdf", "2-s2.pdf", "3-s3.pdf"))
    status = done_status(task)
    result = plan(
        task,
        {"1-s1.pdf": status, "2-s2.pdf": status, "3-s3.pdf": None},
    )
    assert result.nothing_to_do() is False
    assert result.copy_to(status) == ["3-s3.pdf"]


def test_a_later_document_linking_to_a_file_done_before():
    # 1-s1.pdf was done when it was the only key. A Document imported
    # since links to the same file.
    before = make_task(keys=("1-s1.pdf",))
    task = make_task(keys=("1-s1.pdf", "2-s2.pdf"))
    status = done_status(before)
    result = plan(task, {"1-s1.pdf": status, "2-s2.pdf": None})
    assert not result.extract
    # The new Document's decision is in the chunks' metadata.
    assert result.chunk
    assert result.needs_status_update


def test_a_new_primary_key_copies_from_another_key():
    # A decision imported later is now the earliest to link to the file.
    before = make_task(keys=("2-s2.pdf",))
    task = make_task(keys=("1-s1.pdf", "2-s2.pdf"))
    status = done_status(before)
    result = plan(task, {"1-s1.pdf": None, "2-s2.pdf": status})
    assert result.copy_from == "2-s2.pdf"
    assert not result.extract
    assert result.chunk


def test_a_failed_primary_key_copies_from_another_key():
    task = make_task(keys=("1-s1.pdf", "2-s2.pdf"))
    result = plan(
        task,
        {
            "1-s1.pdf": extracted(task, ExtractStatus.FAILED),
            "2-s2.pdf": done_status(task),
        },
    )
    assert result.copy_from == "2-s2.pdf"
    assert not result.extract
    assert not result.chunk


def test_force_does_not_copy():
    task = make_task(keys=("1-s1.pdf", "2-s2.pdf"))
    result = plan(
        task, {"1-s1.pdf": None, "2-s2.pdf": done_status(task)}, force=True
    )
    assert result.copy_from is None
    assert result.extract


def test_a_left_out_file_with_a_new_key():
    before = make_task(keys=("1-s1.pdf",))
    task = make_task(keys=("1-s1.pdf", "2-s2.pdf"))
    status = DocumentStatus(
        content_hash=task.content_hash,
        storage_keys=before.storage_keys,
        format=DocumentFormat.RESTRICTED,
        extract=ExtractEntry(status=ExtractStatus.RESTRICTED),
    )
    result = plan(task, {"1-s1.pdf": status, "2-s2.pdf": None})
    assert not result.needs_worker
    assert result.needs_status_update


def test_nothing_is_copied_from_a_key_with_no_status():
    task = make_task(keys=("1-s1.pdf", "2-s2.pdf"))
    result = plan(
        task,
        {"1-s1.pdf": None, "2-s2.pdf": extracted(task, ExtractStatus.FAILED)},
        stages=[Stage.CHUNK, Stage.EMBED],
    )
    assert result.copy_to(result.status) == []
    assert result.nothing_to_do()
