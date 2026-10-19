import pickle

import pytest
from embeddings.stores import LocalStore, S3Store

from .fakes import FakeS3Client

KEY = "MAN/Decisions/documents/2026-08-06-1172-s65106.pdf"


@pytest.fixture
def local(tmp_path):
    return LocalStore(tmp_path)


@pytest.fixture
def s3():
    store = S3Store("lgsf-data-archive")
    store._client = FakeS3Client()
    return store


@pytest.fixture(params=["local", "s3"])
def store(request):
    return request.getfixturevalue(request.param)


def test_write_and_read(store):
    assert not store.exists(KEY)
    store.write_bytes(KEY, b"%PDF-1.7\n")
    assert store.exists(KEY)
    assert store.read_bytes(KEY) == b"%PDF-1.7\n"


def test_read_missing(store):
    with pytest.raises(FileNotFoundError):
        store.read_bytes(KEY)


def test_list_prefix(store):
    for name in ("b.pdf", "a.pdf", "a.pdf.status.json"):
        store.write_bytes(f"MAN/Decisions/documents/{name}", b"")
    store.write_bytes("MANX/Decisions/documents/c.pdf", b"")
    assert store.list_prefix("MAN/Decisions/documents/") == [
        "MAN/Decisions/documents/a.pdf",
        "MAN/Decisions/documents/a.pdf.status.json",
        "MAN/Decisions/documents/b.pdf",
    ]
    assert store.list_prefix("OLD/Decisions/documents/") == []


def test_copy(store):
    store.write_bytes(KEY, b"one")
    store.copy(KEY, KEY + ".copy")
    assert store.read_bytes(KEY + ".copy") == b"one"


def test_download_to(store, tmp_path):
    store.write_bytes(KEY, b"%PDF-1.7\n")
    path = store.download_to(KEY, tmp_path)
    assert path.read_bytes() == b"%PDF-1.7\n"


def test_download_missing(store, tmp_path):
    with pytest.raises(FileNotFoundError):
        store.download_to(KEY, tmp_path)


def test_local_writes_leave_no_temporary_files(local, tmp_path):
    local.write_bytes(KEY, b"one")
    local.write_bytes(KEY, b"two")
    local.copy(KEY, KEY + ".copy")
    directory = tmp_path / "MAN" / "Decisions" / "documents"
    assert sorted(p.name for p in directory.iterdir()) == [
        "2026-08-06-1172-s65106.pdf",
        "2026-08-06-1172-s65106.pdf.copy",
    ]


def test_local_download_is_the_file_itself(local, tmp_path):
    local.write_bytes(KEY, b"%PDF-1.7\n")
    assert local.download_to(KEY, tmp_path / "elsewhere") == tmp_path / KEY


def test_s3_keys_are_under_the_data_prefix(s3):
    s3.write_bytes(KEY, b"")
    assert list(s3.client.objects) == [("lgsf-data-archive", f"data/{KEY}")]
    assert s3.url(KEY) == f"s3://lgsf-data-archive/data/{KEY}"


def test_s3_store_is_pickled_without_its_client(s3):
    copy = pickle.loads(pickle.dumps(s3))
    assert copy._client is None
    assert (copy.bucket, copy.prefix) == ("lgsf-data-archive", "data/")
