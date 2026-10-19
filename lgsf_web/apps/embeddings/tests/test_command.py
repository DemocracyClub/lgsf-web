"""embed_documents's filters and --dry-run, against made-up files."""

import io

import pytest
from core.models import Document
from django.core.management import CommandError, call_command
from embeddings.sidecars import write_status
from embeddings.stores import LocalStore
from embeddings.tasks import build_tasks

from .factories import create_document
from .test_sidecars import done_status


@pytest.fixture
def data_dir(tmp_path, settings):
    settings.LGSF_DATA_DIR = tmp_path
    return tmp_path


@pytest.fixture
def documents(db, data_dir):
    files = {
        ("MAN", "1", "2026-02-01", "2026-02-01-1-s1.pdf", "aaa"): b"%PDF-1.7",
        ("MAN", "2", "2026-03-01", "2026-03-01-2-s5.pdf", "aaa"): b"%PDF-1.7",
        ("MAN", "2", "2026-03-01", "2026-03-01-2-s6.pdf", "bbb"): (
            b"<html><h1>Reasons restricted</h1></html>"
        ),
        ("OLD", "3", "2026-04-01", "2026-04-01-3-s7.pdf", "ccc"): b"",
    }
    created = {}
    for (council, identifier, date, key, content_hash), data in files.items():
        created[key] = create_document(
            council, identifier, date, key, content_hash
        )
        path = data_dir / council / "Decisions" / "documents" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return created


def dry_run(*args):
    out = io.StringIO()
    call_command("embed_documents", *args, "--dry-run", stdout=out)
    return out.getvalue()


def test_dry_run(documents):
    output = dry_run()
    assert output.startswith("4 documents, in 3 files")
    assert "        1  pdf\n" in output
    assert "        1  restricted\n" in output
    assert "        1  empty\n" in output
    assert "        3  extract\n" in output


def test_councils(documents):
    assert dry_run("man").startswith("3 documents, in 2 files")


def test_dates(documents):
    assert dry_run("--since", "2026-03-01", "--until", "2026-03-31").startswith(
        # 2026-03-01-2-s5.pdf's file is also linked from decision 1.
        "3 documents, in 2 files"
    )


def test_document(documents):
    document = documents["2026-04-01-3-s7.pdf"]
    assert dry_run("--document", str(document.id)).startswith(
        "1 documents, in 1 files"
    )


def test_limit(documents):
    assert dry_run("--limit", "1").startswith("2 documents, in 1 files")


def test_missing_files_are_counted(documents, data_dir):
    (
        data_dir / "OLD" / "Decisions" / "documents" / "2026-04-01-3-s7.pdf"
    ).unlink()
    assert "        1  missing\n" in dry_run()


def test_status_is_read(documents, data_dir):

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
