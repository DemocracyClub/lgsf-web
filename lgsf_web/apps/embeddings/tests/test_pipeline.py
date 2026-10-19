"""
Running the stages, and running them again.

Docling isn't loaded: extract.convert() is replaced with one that
returns the MAN decision notice from fixtures/, whatever it's given, and
files are worked on in threads rather than worker processes. The
embedder is a fake. The files are made up in a temporary directory.
"""

import dataclasses
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from embeddings import extract, pipeline
from embeddings.extract import ExtractStatus
from embeddings.sidecars import Stage, read_status
from embeddings.stores import LocalStore

from .factories import make_task
from .fakes import FakeEmbedder

FIXTURES = Path(__file__).parent / "fixtures"
MAN_DOCLING = FIXTURES / "MAN" / "2026-08-06-1172-s65106.pdf.docling.json"

PDF = b"%PDF-1.7\nA made-up PDF"
RESTRICTED = (FIXTURES / "OLD" / "2026-01-19-5611-4.pdf").read_bytes()

ALL_STAGES = list(Stage)
SIDECARS = ["chunks.jsonl", "docling.json", "fake.jsonl", "md", "status.json"]


@pytest.fixture
def converted(monkeypatch):
    """The names of the streams extract.convert() is given."""
    docling_core = pytest.importorskip("docling_core.types.doc")
    document = docling_core.DoclingDocument.load_from_json(MAN_DOCLING)
    names = []

    def convert(stream):
        names.append(stream.name)
        return extract.Conversion(ExtractStatus.OK, 2, None, document)

    monkeypatch.setattr(extract, "convert", convert)
    monkeypatch.setattr(extract, "docling_version", lambda: "2.130.0")
    monkeypatch.setattr(extract, "converter_device", lambda: "cpu")
    return names


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path)


def add_file(store, data, keys=("2026-02-01-1-s1.pdf",)):
    """A file stored under each key, and its task."""
    content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
    task = make_task(council="MAN", content_hash=content_hash, keys=keys)
    for key in keys:
        store.write_bytes(task.document_key(key), data)
    return task


def run(store, tasks, stages=ALL_STAGES, embedder=None, **options):
    embedder = embedder or FakeEmbedder()
    plans, _ = pipeline.plan_tasks(
        tasks,
        store,
        stages,
        [embedder.name],
        retry_failed=options.pop("retry_failed", False),
        force=options.get("force", False),
    )
    outcomes = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        pipeline.run(
            plans,
            store,
            [embedder],
            pipeline.Options(stages=stages, **options),
            executor,
            outcomes.append,
        )
    return outcomes


def sidecars(store, task, key=None):
    """The sidecar files next to a storage key, by suffix."""
    document_key = task.document_key(key or task.primary.storage_key)
    return sorted(
        name.removeprefix(f"{document_key}.")
        for name in store.list_prefix(f"{document_key}.")
    )


def status(store, task, key=None):
    return read_status(
        store, task.document_key(key or task.primary.storage_key)
    )


# A first run


def test_a_pdf_gets_every_sidecar(store, converted):
    task = add_file(store, PDF)
    embedder = FakeEmbedder()
    [outcome] = run(store, [task], embedder=embedder)
    assert outcome.error is None
    assert sidecars(store, task) == SIDECARS
    assert converted == ["2026-02-01-1-s1.pdf"]

    result = status(store, task)
    assert result.extract.status == ExtractStatus.OK
    assert result.extract.pages == 2
    assert result.extract.docling_version == "2.130.0"
    assert result.chunk.chunks == 4
    assert result.chunk.embeddable == 3
    assert result.embed["fake"].embedded == 3
    assert len(embedder.texts) == 3


def test_sidecar_contents(store, converted):
    task = add_file(store, PDF)
    run(store, [task])
    key = task.document_key(task.primary.storage_key)
    chunks = [
        json.loads(line)
        for line in store.read_bytes(f"{key}.chunks.jsonl").splitlines()
    ]
    assert [c["chunk_index"] for c in chunks] == [0, 1, 2, 3]
    assert chunks[1]["context"].startswith("Test Council · Cabinet")
    records = [
        json.loads(line)
        for line in store.read_bytes(f"{key}.fake.jsonl").splitlines()
    ]
    assert [r["chunk_id"] for r in records] == [
        c["chunk_id"] for c in chunks if c["embed"]
    ]
    assert b"Notice of Decision Made" in store.read_bytes(f"{key}.md")
    assert json.loads(store.read_bytes(f"{key}.docling.json"))["name"]


@pytest.mark.parametrize(
    ("data", "extract_status"),
    [
        (RESTRICTED, ExtractStatus.RESTRICTED),
        (b"<html><body>Logon</body></html>", ExtractStatus.NOT_DOCUMENT),
        (b"", ExtractStatus.EMPTY),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00", ExtractStatus.UNSUPPORTED),
    ],
)
def test_left_out_files_only_get_a_status(
    store, converted, data, extract_status
):
    task = add_file(store, data)
    run(store, [task])
    assert sidecars(store, task) == ["status.json"]
    assert status(store, task).extract.status == extract_status
    assert converted == []


def test_text_is_converted_as_markdown(store, converted):
    data = (FIXTURES / "BUR" / "2015-12-16-995-s9686.txt").read_bytes()
    task = add_file(store, data, keys=("2015-12-16-995-s9686.txt",))
    run(store, [task], stages=[Stage.EXTRACT])
    assert converted == ["2015-12-16-995-s9686.md"]
    assert status(store, task).format == "text"


def test_a_file_that_has_changed_fails(store, converted):
    task = add_file(store, PDF)
    store.write_bytes(task.document_key(task.primary.storage_key), b"%PDF-2")
    run(store, [task])
    result = status(store, task)
    assert result.extract.status == ExtractStatus.FAILED
    assert "hash" in result.extract.error
    assert converted == []


def test_a_missing_file_is_not_recorded(store, converted):
    task = make_task(council="MAN")
    [outcome] = run(store, [task])
    assert outcome.result.missing
    assert sidecars(store, task) == []


def test_long_pdfs_are_left_for_later(store, converted, monkeypatch):
    monkeypatch.setattr(extract, "count_pages", lambda data: 500)
    task = add_file(store, PDF)
    [outcome] = run(store, [task], max_pages=100)
    assert outcome.result.too_long == 500
    assert sidecars(store, task) == []
    run(store, [task])
    assert status(store, task).extract.status == ExtractStatus.OK


def test_a_conversion_that_raises_is_failed(store, converted, monkeypatch):
    def convert(stream):
        raise RuntimeError("Docling broke")

    monkeypatch.setattr(extract, "convert", convert)
    task = add_file(store, PDF)
    run(store, [task])
    result = status(store, task)
    assert result.extract.status == ExtractStatus.FAILED
    assert result.extract.error == "RuntimeError: Docling broke"
    assert sidecars(store, task) == ["status.json"]


# Running again


def test_running_again_does_nothing(store, converted):
    task = add_file(store, PDF)
    run(store, [task])
    first = status(store, task)
    embedder = FakeEmbedder()
    assert run(store, [task], embedder=embedder) == []
    assert converted == ["2026-02-01-1-s1.pdf"]
    assert embedder.texts == []
    assert status(store, task) == first


def test_a_deleted_status_is_done_again(store, converted):
    tasks = [
        add_file(store, PDF),
        add_file(store, b"%PDF-1.7\nAnother", keys=("2026-02-01-1-s2.pdf",)),
    ]
    run(store, tasks)
    assert len(converted) == 2
    key = tasks[0].document_key(tasks[0].primary.storage_key)
    Path(store.path(f"{key}.status.json")).unlink()
    outcomes = run(store, tasks)
    assert [o.plan.task for o in outcomes] == [tasks[0]]
    assert len(converted) == 3


def test_failures_are_retried_when_asked(store, converted):
    task = add_file(store, PDF)
    store.write_bytes(task.document_key(task.primary.storage_key), b"%PDF-2")
    run(store, [task])
    store.write_bytes(task.document_key(task.primary.storage_key), PDF)
    assert run(store, [task]) == []
    run(store, [task], retry_failed=True)
    assert status(store, task).extract.status == ExtractStatus.OK


def test_force(store, converted):
    task = add_file(store, PDF)
    run(store, [task])
    embedder = FakeEmbedder()
    run(store, [task], embedder=embedder, force=True)
    assert len(converted) == 2
    assert len(embedder.texts) == 3


def test_a_new_chunker_version(store, converted, monkeypatch):
    task = add_file(store, PDF)
    run(store, [task])
    monkeypatch.setattr("embeddings.chunking.CHUNKER_VERSION", 999)
    embedder = FakeEmbedder()
    [outcome] = run(store, [task], embedder=embedder)
    # Chunked and embedded again, but not converted again, and the chunks'
    # text is the same, so every embedding is reused.
    assert converted == ["2026-02-01-1-s1.pdf"]
    assert outcome.result.chunk is not None
    assert embedder.texts == []
    assert status(store, task).embed["fake"].reused == 3


def test_a_retitled_decision(store, converted):
    task = add_file(store, PDF)
    run(store, [task])
    document = task.documents[0]
    task.documents[0] = dataclasses.replace(
        document,
        decision=dataclasses.replace(document.decision, title="Retitled"),
    )
    embedder = FakeEmbedder()
    run(store, [task], embedder=embedder)
    assert converted == ["2026-02-01-1-s1.pdf"]
    # The header is in every chunk's embedded text.
    assert len(embedder.texts) == 3
    assert all("Decision: Retitled" in text for text in embedder.texts)


def test_stages_one_at_a_time(store, converted):
    task = add_file(store, PDF)
    run(store, [task], stages=[Stage.EXTRACT])
    assert sidecars(store, task) == ["docling.json", "md", "status.json"]
    run(store, [task], stages=[Stage.CHUNK])
    assert sidecars(store, task) == [
        "chunks.jsonl",
        "docling.json",
        "md",
        "status.json",
    ]
    run(store, [task], stages=[Stage.EMBED])
    assert sidecars(store, task) == SIDECARS
    assert converted == ["2026-02-01-1-s1.pdf"]


def test_chunking_without_embedding_leaves_the_embeddings_to_redo(
    store, converted, monkeypatch
):
    task = add_file(store, PDF)
    run(store, [task])
    monkeypatch.setattr("embeddings.chunking.CHUNKER_VERSION", 999)
    run(store, [task], stages=[Stage.CHUNK])
    assert "fake.jsonl" not in status(store, task).sidecars()
    run(store, [task], stages=[Stage.EMBED])
    assert status(store, task).embedded("fake")


# Errors


class BrokenEmbedder(FakeEmbedder):
    def embed_documents(self, texts):
        raise RuntimeError("ThrottlingException")


def test_an_embedding_error_is_recorded_and_retried(store, converted):
    tasks = [
        add_file(store, PDF),
        add_file(store, RESTRICTED, keys=("2026-02-01-1-s2.pdf",)),
    ]
    outcomes = run(store, tasks, embedder=BrokenEmbedder())
    # The run carried on.
    assert len(outcomes) == 2
    entry = status(store, tasks[0]).embed["fake"]
    assert entry.error == "RuntimeError: ThrottlingException"
    assert "fake.jsonl" not in sidecars(store, tasks[0])

    embedder = FakeEmbedder()
    [outcome] = run(store, tasks, embedder=embedder)
    assert outcome.result.extract is None
    assert len(embedder.texts) == 3
    assert status(store, tasks[0]).embed["fake"].error is None


def test_a_chunking_error_is_recorded_and_retried(store, converted):
    task = add_file(store, PDF)
    run(store, [task], stages=[Stage.EXTRACT])
    key = task.document_key(task.primary.storage_key)
    good = store.read_bytes(f"{key}.docling.json")
    store.write_bytes(f"{key}.docling.json", b"{")
    run(store, [task])
    result = status(store, task)
    assert result.chunk.error.startswith("ValidationError")
    assert result.embed == {}

    store.write_bytes(f"{key}.docling.json", good)
    run(store, [task])
    assert status(store, task).chunked
    assert converted == ["2026-02-01-1-s1.pdf"]


# Several storage keys


def test_every_key_gets_the_full_set(store, converted):
    keys = ("2026-02-01-1-s1.pdf", "2026-02-02-2-s2.pdf", "2026-02-03-3-s3.pdf")
    task = add_file(store, PDF, keys=keys)
    [outcome] = run(store, [task])
    assert converted == ["2026-02-01-1-s1.pdf"]
    assert outcome.copied_to == list(keys[1:])
    primary = task.document_key(keys[0])
    for key in keys:
        assert sidecars(store, task, key) == SIDECARS
        for suffix in SIDECARS:
            assert store.read_bytes(
                f"{task.document_key(key)}.{suffix}"
            ) == store.read_bytes(f"{primary}.{suffix}")
    assert status(store, task).storage_keys == list(keys)
    assert run(store, [task]) == []


def test_a_document_imported_later(store, converted):
    task = add_file(store, PDF, keys=("2026-02-01-1-s1.pdf",))
    run(store, [task])
    # A later decision links to the same file.
    later = add_file(
        store, PDF, keys=("2026-02-01-1-s1.pdf", "2026-02-02-2-s2.pdf")
    )
    embedder = FakeEmbedder()
    [outcome] = run(store, [later], embedder=embedder)
    assert converted == ["2026-02-01-1-s1.pdf"]
    assert outcome.copied_to == ["2026-02-02-2-s2.pdf"]
    # The header still names the first decision, so nothing's embedded
    # again, but the metadata lists both.
    assert embedder.texts == []
    assert sidecars(store, later, "2026-02-02-2-s2.pdf") == SIDECARS
    chunks = store.read_bytes(
        later.document_key("2026-02-02-2-s2.pdf") + ".chunks.jsonl"
    )
    decisions = json.loads(chunks.splitlines()[0])["metadata"]["decisions"]
    assert [d["identifier"] for d in decisions] == ["1", "2"]


def test_a_new_primary_key_is_copied_to_not_converted(store, converted):
    task = add_file(store, PDF, keys=("2026-02-02-2-s2.pdf",))
    run(store, [task])
    # An earlier decision, imported since, links to the same file.
    task = add_file(
        store, PDF, keys=("2026-02-01-1-s1.pdf", "2026-02-02-2-s2.pdf")
    )
    embedder = FakeEmbedder()
    [outcome] = run(store, [task], embedder=embedder)
    assert outcome.plan.copy_from == "2026-02-02-2-s2.pdf"
    assert converted == ["2026-02-02-2-s2.pdf"]
    # The headers name the earlier decision now.
    assert len(embedder.texts) == 3
    for key in task.storage_keys:
        assert sidecars(store, task, key) == SIDECARS
        assert status(store, task, key) == status(store, task)


def test_a_restricted_page_with_a_new_key(store, converted):
    task = add_file(store, RESTRICTED, keys=("2026-02-01-1-s1.pdf",))
    run(store, [task])
    task = add_file(
        store, RESTRICTED, keys=("2026-02-01-1-s1.pdf", "2026-02-02-2-s2.pdf")
    )
    [outcome] = run(store, [task])
    assert outcome.result.extract is None
    assert sidecars(store, task, "2026-02-02-2-s2.pdf") == ["status.json"]
    assert status(store, task, "2026-02-02-2-s2.pdf").storage_keys == list(
        task.storage_keys
    )


def test_stopping_while_the_parent_embeds(store, converted):
    task = add_file(store, PDF)
    run(store, [task], stages=[Stage.EXTRACT, Stage.CHUNK])

    class StoppedEmbedder(FakeEmbedder):
        def embed_documents(self, texts):
            raise KeyboardInterrupt

    plans, _ = pipeline.plan_tasks([task], store, ALL_STAGES, ["fake"])
    with pytest.raises(KeyboardInterrupt):
        pipeline.run(
            plans,
            store,
            [StoppedEmbedder()],
            pipeline.Options(stages=ALL_STAGES),
            executor=None,
        )
