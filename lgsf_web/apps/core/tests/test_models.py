import datetime

import pytest
from core.models import Decision, Document


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
