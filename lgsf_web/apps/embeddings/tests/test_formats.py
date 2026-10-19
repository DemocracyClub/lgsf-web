"""
detect_format(), against files copied from data/ where there's one to
copy, and made up where there isn't. Each is stored under its storage
key.
"""

import zipfile
from pathlib import Path

import pytest
from embeddings.formats import (
    DocumentFormat,
    detect_format,
    stream_name,
    unwrap_multipart,
)

FIXTURES = Path(__file__).parent / "fixtures"
MULTIPART_PDF = FIXTURES / "NTL" / "2024-12-11-4863-s103135.pdf"


@pytest.mark.parametrize(
    "path",
    [
        # Each council's page has its own markup around the heading.
        "FLN/2019-06-18-7123-2.pdf",
        "OLD/2026-01-19-5611-4.pdf",
        "AGY/2026-03-24-4034-1.pdf",
        "SLF/2026-01-12-3923-2.pdf",
        # The heading is an <h3>.
        "TRF/2021-09-07-1051-2.pdf",
    ],
)
def test_restricted_pages(path):
    assert detect_format(FIXTURES / path) == DocumentFormat.RESTRICTED


def test_other_html_pages():
    # A Tameside logon page, saved in place of a report.
    path = FIXTURES / "TAM" / "2026-04-22-2959-s204151.pdf"
    assert detect_format(path) == DocumentFormat.HTML


def test_empty_file():
    path = FIXTURES / "BUR" / "2020-12-18-3451-s25739.pdf"
    assert path.stat().st_size == 0
    assert detect_format(path) == DocumentFormat.EMPTY


def test_file_of_zero_bytes(tmp_path):
    path = tmp_path / "2022-02-14-821-s64643.pdf"
    path.write_bytes(b"\x00" * 100_000)
    assert detect_format(path) == DocumentFormat.EMPTY


def test_zero_bytes_then_something(tmp_path):
    path = tmp_path / "2022-02-14-821-s64643.pdf"
    path.write_bytes(b"\x00" * 100_000 + b"\x01")
    assert detect_format(path) == DocumentFormat.UNSUPPORTED


def test_pdf(tmp_path):
    path = tmp_path / "2026-08-06-1172-s65106.pdf"
    path.write_bytes(b"%PDF-1.7\n")
    assert detect_format(path) == DocumentFormat.PDF


def test_multipart_pdf():
    assert detect_format(MULTIPART_PDF) == DocumentFormat.MULTIPART_PDF


def test_unwrap_multipart():
    pdf = unwrap_multipart(MULTIPART_PDF.read_bytes())
    assert pdf.startswith(b"%PDF-1.5\r\n")
    assert pdf.endswith(b"%%EOF\r\n")


def test_unwrap_multipart_without_a_closing_boundary():
    data = MULTIPART_PDF.read_bytes()
    with pytest.raises(ValueError):
        unwrap_multipart(data[: len(data) // 2])


def test_docx():
    path = FIXTURES / "NTL" / "2019-10-24-2201-s54786.pdf"
    assert detect_format(path) == DocumentFormat.DOCX


@pytest.mark.parametrize(
    ("member", "document_format"),
    [
        ("xl/workbook.xml", DocumentFormat.XLSX),
        ("ppt/presentation.xml", DocumentFormat.PPTX),
        # DEN's ZIP of traffic order plans
        ("Moel Famau TRO_Plans/10_BB95.pdf", DocumentFormat.UNSUPPORTED),
    ],
)
def test_other_zips(tmp_path, member, document_format):
    path = tmp_path / "2022-03-15-1957-s46050.pdf"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, b"")
    assert detect_format(path) == document_format


def test_text_email():
    path = FIXTURES / "BUR" / "2015-12-16-995-s9686.txt"
    assert detect_format(path) == DocumentFormat.TEXT


def test_csv(tmp_path):
    path = tmp_path / "2026-01-01-1-s1.csv"
    path.write_bytes(b"Applicant,Amount\r\nSeaton Hall,1395\r\n")
    assert detect_format(path) == DocumentFormat.CSV


@pytest.mark.parametrize(
    "signature",
    [
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff\xe0",
        b"II*\x00",
        b"RIFF\0\0\0\0WEBP",
    ],
)
def test_images(tmp_path, signature):
    path = tmp_path / "2026-01-01-1-s1.pdf"
    path.write_bytes(signature + b"\x00\x01\x02")
    assert detect_format(path) == DocumentFormat.IMAGE


def test_other_binary_files(tmp_path):
    # An old Word document
    path = tmp_path / "2026-01-01-1-s1.pdf"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00\x00")
    assert detect_format(path) == DocumentFormat.UNSUPPORTED


def test_stream_name():
    assert (
        stream_name("2015-12-16-995-s9686.txt", DocumentFormat.TEXT)
        == "2015-12-16-995-s9686.md"
    )
    assert (
        stream_name("2019-10-24-2201-s54786.pdf", DocumentFormat.DOCX)
        == "2019-10-24-2201-s54786.docx"
    )
    assert (
        stream_name("2024-12-11-4863-s103135.pdf", DocumentFormat.MULTIPART_PDF)
        == "2024-12-11-4863-s103135.pdf"
    )


def test_left_out_formats_have_no_stream_name():
    with pytest.raises(KeyError):
        stream_name("2026-01-28-2856-5.pdf", DocumentFormat.RESTRICTED)
