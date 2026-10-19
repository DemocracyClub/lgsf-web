"""
split_document(), and the table serializer it uses, against a real MAN
decision notice: D3 P-1475, linked from decision 1172 of 6 August 2026,
converted with Docling 2.130.0.

It's two pages of tables of labels and values, with no header rows, in
four sections.

These tests need docling-core, from the embeddings dependency group,
and are skipped without it.
"""

from pathlib import Path

import pytest

pytest.importorskip("docling_core")

import pandas as pd
from docling_core.types.doc import DoclingDocument
from embeddings.documents import split_document, table_lines

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def parts():
    document = DoclingDocument.load_from_json(
        FIXTURES / "MAN" / "2026-08-06-1172-s65106.pdf.docling.json"
    )
    return split_document(document)


def test_parts(parts):
    assert len(parts) == 4
    assert parts[0].text == "Made by an Executive Member or Chief Officer"


def test_headings_and_pages(parts):
    assert parts[1].headings == ["Notice of Decision Made"]
    assert parts[1].pages == [1, 2]


def test_tables_with_no_header_row_are_labels_and_values(parts):
    lines = parts[1].text.split("\n")
    assert lines[:2] == [
        "Decision maker: City Treasurer and Interim Deputy Chief Executive",
        "Date of decision: 6 August 2026",
    ]
    assert ", 1 =" not in "\n".join(part.text for part in parts)


def test_max_words():
    document = DoclingDocument.load_from_json(
        FIXTURES / "MAN" / "2026-08-06-1172-s65106.pdf.docling.json"
    )
    parts = split_document(document, max_words=20)
    assert len(parts) > 4
    assert all(len(part.text.split()) <= 20 for part in parts)


def test_table_with_no_header_row():
    table = pd.DataFrame(
        [
            ["Decision maker", "City Treasurer"],
            ["Spans both columns", "Spans both columns"],
            ["Not filled in", ""],
            ["Two values", "One"],
        ]
    )
    table[2] = ["", "", "", "Two"]
    assert table_lines(table) == [
        "Decision maker: City Treasurer",
        "Spans both columns",
        "Not filled in",
        "Two values: One | Two",
    ]


def test_table_with_a_header_row():
    table = pd.DataFrame(
        [
            ["Axewoods Co-Op", "£1,395", "Agreed"],
            ["Seaton Hall", "", "Deferred"],
        ],
        columns=["Applicant", "Amount", "Decision"],
    )
    assert table_lines(table) == [
        "Axewoods Co-Op, Amount = £1,395. Axewoods Co-Op, Decision = Agreed",
        "Seaton Hall, Decision = Deferred",
    ]


def test_table_with_only_a_header_row():
    table = pd.DataFrame([], columns=["Applicant", "Amount"])
    assert table_lines(table) == ["Applicant | Amount"]
