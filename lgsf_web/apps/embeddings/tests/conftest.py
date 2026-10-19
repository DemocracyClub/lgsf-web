import pytest

from .factories import create_document


@pytest.fixture
def data_dir(tmp_path, settings):
    settings.LGSF_DATA_DIR = tmp_path
    return tmp_path


@pytest.fixture
def documents_on_disk(db, data_dir):
    """
    Four Documents in the database, and their files in LGSF_DATA_DIR:
    a PDF linked from two decisions, a restricted page and an empty file.
    """
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
