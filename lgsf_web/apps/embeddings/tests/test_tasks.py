"""Building tasks from the database, sharding them, and manifests."""

import json

import pytest
from core.models import Document
from embeddings.tasks import (
    build_tasks,
    read_manifest,
    shard,
    write_manifest,
)

from .factories import create_document, make_task


@pytest.fixture
def documents(db):
    """
    Three decisions in MAN. The report "aaa" is linked from all three,
    under a different key each time. OLD has a file with the same hash.
    """
    create_document("MAN", "2", "2026-03-01", "2026-03-01-2-s5.pdf", "aaa")
    create_document("MAN", "2", "2026-03-01", "2026-03-01-2-s6.pdf", "bbb")
    create_document("MAN", "1", "2026-02-01", "2026-02-01-1-s1.pdf", "aaa")
    create_document("MAN", "3", "2026-04-01", "2026-04-01-3-s7.pdf", "aaa")
    create_document("OLD", "9", "2026-01-01", "2026-01-01-9-s1.pdf", "aaa")


def test_a_task_for_each_council_and_hash(documents):
    tasks = build_tasks(Document.objects.all())
    assert [(t.council, t.content_hash) for t in tasks] == [
        ("OLD", "aaa"),
        ("MAN", "aaa"),
        ("MAN", "bbb"),
    ]


def test_documents_are_in_decision_date_order(documents):
    task = build_tasks(Document.objects.filter(decision__council="MAN"))[0]
    assert task.storage_keys == [
        "2026-02-01-1-s1.pdf",
        "2026-03-01-2-s5.pdf",
        "2026-04-01-3-s7.pdf",
    ]
    assert task.primary.decision.identifier == "1"
    assert task.primary.decision.date == "2026-02-01"


def test_task_fields(documents):
    task = build_tasks(Document.objects.filter(content_hash="bbb"))[0]
    document = Document.objects.get(storage_key="2026-03-01-2-s6.pdf")
    assert task.council == "MAN"
    assert task.council_name == "Manchester City Council"
    assert task.content_length == document.content_length
    assert task.primary.id == document.id
    assert task.primary.url == document.url
    assert task.primary.decision.id == document.decision.id
    assert task.primary.decision.url == document.decision.url
    assert task.primary.decision.decision_maker == "Cabinet"


def test_filters_only_choose_the_files(documents):
    # Only the latest decision is chosen, but its file's task has every
    # Document linking to it, so it's the same task either way.
    chosen = Document.objects.filter(decision__raw_date__gte="2026-04-01")
    [task] = build_tasks(chosen)
    everything = build_tasks(Document.objects.filter(decision__council="MAN"))
    assert task == everything[0]


def test_limit_counts_tasks(documents):
    tasks = build_tasks(Document.objects.filter(decision__council="MAN"), 1)
    assert [len(t.documents) for t in tasks] == [3]


def test_documents_without_a_hash_are_left_out(documents):
    create_document("MAN", "4", "2026-05-01", "2026-05-01-4-s8.pdf", "")
    assert (
        len(build_tasks(Document.objects.filter(decision__council="MAN"))) == 2
    )


def test_shards_are_balanced_by_size():
    tasks = [
        make_task(content_hash=f"sha256:{size}") for size in (9, 1, 5, 4, 3)
    ]
    for task, size in zip(tasks, (9, 1, 5, 4, 3), strict=True):
        task.content_length = size
    shards = shard(tasks, 2)
    assert [[t.content_length for t in s] for s in shards] == [
        [9, 3],
        [5, 4, 1],
    ]


def test_every_shard_is_returned():
    assert shard([make_task()], 3)[1:] == [[], []]


def test_manifest_round_trip(tmp_path):
    shards = [[make_task(keys=("1-s1.pdf", "2-s2.pdf"))], [make_task()]]
    paths = write_manifest(tmp_path / "run", shards, {"filters": {}})
    assert [p.name for p in paths] == ["shard-00000.jsonl", "shard-00001.jsonl"]
    assert read_manifest(str(tmp_path / "run"), 0) == shards[0]
    assert read_manifest(str(tmp_path / "run"), 1) == shards[1]
    run = json.loads((tmp_path / "run" / "run.json").read_text())
    assert run == {"filters": {}}
