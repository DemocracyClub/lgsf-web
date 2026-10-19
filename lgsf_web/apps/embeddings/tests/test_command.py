"""embed_documents's filters and --dry-run, against made-up files."""

import io

import pytest
from core.models import Document
from django.core.management import CommandError, call_command
from embeddings.sidecars import write_status
from embeddings.stores import LocalStore
from embeddings.tasks import build_tasks

from .test_sidecars import done_status


def dry_run(*args):
    out = io.StringIO()
    call_command("embed_documents", *args, "--dry-run", stdout=out)
    return out.getvalue()


def test_dry_run(documents_on_disk):
    output = dry_run()
    assert output.startswith("4 documents, in 3 files")
    assert "        1  pdf\n" in output
    assert "        1  restricted\n" in output
    assert "        1  empty\n" in output
    assert "        3  extract\n" in output


def test_councils(documents_on_disk):
    assert dry_run("man").startswith("3 documents, in 2 files")


def test_dates(documents_on_disk):
    assert dry_run("--since", "2026-03-01", "--until", "2026-03-31").startswith(
        # 2026-03-01-2-s5.pdf's file is also linked from decision 1.
        "3 documents, in 2 files"
    )


def test_document(documents_on_disk):
    document = documents_on_disk["2026-04-01-3-s7.pdf"]
    assert dry_run("--document", str(document.id)).startswith(
        "1 documents, in 1 files"
    )


def test_limit(documents_on_disk):
    assert dry_run("--limit", "1").startswith("2 documents, in 1 files")


def test_missing_files_are_counted(documents_on_disk, data_dir):
    (
        data_dir / "OLD" / "Decisions" / "documents" / "2026-04-01-3-s7.pdf"
    ).unlink()
    assert "        1  missing\n" in dry_run()


def test_status_is_read(documents_on_disk, data_dir):

    [task] = build_tasks(Document.objects.filter(content_hash="aaa"))
    write_status(
        LocalStore(data_dir),
        task.document_key(task.primary.storage_key),
        done_status(task),
    )
    output = dry_run("MAN")
    assert "        1  ok\n" in output
    # The second key of the done file needs the files copying to it.
    assert "        1  copy\n" in output


def test_invalid_stages():
    with pytest.raises(CommandError, match="Invalid stages"):
        call_command("embed_documents", "--stages", "extract,other")


def test_invalid_date():
    with pytest.raises(CommandError, match="Invalid date"):
        call_command("embed_documents", "--since", "2026-13-01")
