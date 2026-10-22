import datetime

import pytest
from core.models import Chunk, Decision, Document


@pytest.mark.django_db
def test_document_s3_url(settings):
    settings.LGSF_DATA_BUCKET = "example-bucket"
    decision = Decision.objects.create(
        council_id="MAN",
        raw_identifier="1172",
        raw_date=datetime.date(2026, 8, 6),
        url="https://democracy.manchester.gov.uk/ieDecisionDetails.aspx?ID=1172",
    )
    document = Document.objects.create(
        decision=decision,
        url="https://democracy.manchester.gov.uk/documents/s65106/D3.pdf",
        storage_key="2026-08-06-1172-s65106.pdf",
    )
    assert document.s3_url == (
        "https://example-bucket.s3.eu-west-2.amazonaws.com/data/MAN/"
        "Decisions/documents/2026-08-06-1172-s65106.pdf"
    )


def test_text_for_display_bolds_terms_case_insensitively():
    chunk = Chunk(text="The Housing policy <b>changed</b>.")
    assert chunk.text_for_display("housing CHANGED") == (
        "The <strong>Housing</strong> policy "
        "&lt;b&gt;<strong>changed</strong>&lt;/b&gt;."
    )


def test_text_for_display_without_match_returns_start_of_text():
    chunk = Chunk(text="word " * 100)
    result = chunk.text_for_display("zebra")
    assert "<strong>" not in result
    assert result.endswith("…")


def test_text_for_display_windows_around_first_match():
    chunk = Chunk(text=" ".join(f"w{i}" for i in range(200)) + " needle")
    result = chunk.text_for_display("needle")
    assert result.startswith("…")
    assert "<strong>needle</strong>" in result
