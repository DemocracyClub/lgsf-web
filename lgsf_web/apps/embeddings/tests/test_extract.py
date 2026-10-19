"""
Converting files through a DocumentStream, with Docling's own converter.

Only the DOCX and the text email are converted: Docling reads them
without models. PDFs and images need the layout model, TableFormer and
OCR, which aren't loaded in tests.
"""

from pathlib import Path

import pytest

pytest.importorskip("docling")

from embeddings import extract
from embeddings.chunking import chunk_document
from embeddings.extract import ExtractStatus
from embeddings.formats import DocumentFormat, detect_format
from embeddings.records import SourceType

from .factories import make_task

FIXTURES = Path(__file__).parent / "fixtures"


def convert(path, storage_key):
    document_format = detect_format(path)
    data = extract.document_bytes(path, document_format)
    stream = extract.document_stream(data, storage_key, document_format)
    return document_format, extract.convert(stream)


def test_docx():
    document_format, conversion = convert(
        FIXTURES / "NTL" / "2019-10-24-2201-s54786.pdf",
        "2019-10-24-2201-s54786.pdf",
    )
    assert document_format == DocumentFormat.DOCX
    assert conversion.status == ExtractStatus.OK
    text = conversion.document.export_to_markdown()
    assert "Leadership Strategy in Schools" in text

    chunks = chunk_document(make_task(), conversion.document, document_format)
    assert chunks
    assert {c.source_type for c in chunks} == {SourceType.DOCX_DOCLING}
    assert "Purpose of the Report" in "\n".join(c.text for c in chunks)


def test_text_email():
    document_format, conversion = convert(
        FIXTURES / "BUR" / "2015-12-16-995-s9686.txt",
        "2015-12-16-995-s9686.txt",
    )
    assert document_format == DocumentFormat.TEXT
    assert conversion.status == ExtractStatus.OK
    assert "Radcliffe Civic Suite" in conversion.document.export_to_markdown()

    chunks = chunk_document(make_task(), conversion.document, document_format)
    assert {c.source_type for c in chunks} == {SourceType.TEXT_DOCLING}
    assert "lodge my objection" in "\n".join(c.text for c in chunks)


def test_docling_json_round_trip():
    _, conversion = convert(
        FIXTURES / "BUR" / "2015-12-16-995-s9686.txt",
        "2015-12-16-995-s9686.txt",
    )
    data = extract.docling_json(conversion.document)
    assert extract.load_docling_json(data) == conversion.document


def test_count_pages():
    assert extract.count_pages(b"%PDF-1.7 not really") is None
    pdf = extract.document_bytes(
        FIXTURES / "NTL" / "2024-12-11-4863-s103135.pdf",
        DocumentFormat.MULTIPART_PDF,
    )
    assert extract.count_pages(pdf) == 11
