"""Tasks for the tests, made up or copied from the database."""

from embeddings.tasks import LinkedDecision, LinkedDocument, Task

MAN_CONTENT_HASH = (
    "sha256:98e2faaa9eb4bb6ef4228d195741b9e86422805963dd641cc9a4fa72869ecee7"
)


def man_document(**decision_fields):
    """
    The MAN decision notice in fixtures/MAN, as lgsf-web's database has
    it: document 3201, linked from decision 1172 of 6 August 2026.
    """
    decision = {
        "id": 1810,
        "identifier": "1172",
        "title": "P-1475 Domestic Abuse - Intersecting Needs Safe "
        "Accommodation (2026/06/09A)",
        "decision_maker": "Strategic Director (Corporate Services) & City "
        "Treasurer",
        "date": "2026-08-06",
        "url": "https://democracy.manchester.gov.uk/ieDecisionDetails.aspx"
        "?ID=1172",
        **decision_fields,
    }
    return LinkedDocument(
        id=3201,
        storage_key="2026-08-06-1172-s65106.pdf",
        title="D3 P-1475 Domestic Abuse - Intersecting Needs Safe "
        "Accommodation",
        url="https://democracy.manchester.gov.uk/documents/s65106/D3 P-1475 "
        "Domestic Abuse - Intersecting Needs Safe Accommodation.pdf",
        decision=LinkedDecision(**decision),
    )


def man_task(*documents):
    return Task(
        council="MAN",
        council_name="Manchester City Council",
        content_hash=MAN_CONTENT_HASH,
        content_length=90680,
        documents=list(documents) or [man_document()],
    )


def make_task(council="TST", content_hash="sha256:aaa", keys=("1-s1.pdf",)):
    """A task linked from one made-up decision for each storage key."""
    documents = [
        LinkedDocument(
            id=index,
            storage_key=key,
            title=f"Document {key}",
            url=f"https://example.org/{key}",
            decision=LinkedDecision(
                id=index,
                identifier=str(index),
                title=f"Decision {index}",
                decision_maker="Cabinet",
                date=f"2026-02-{index:02d}",
                url=f"https://example.org/decisions/{index}",
            ),
        )
        for index, key in enumerate(keys, start=1)
    ]
    return Task(
        council=council,
        council_name="Test Council",
        content_hash=content_hash,
        content_length=1000,
        documents=documents,
    )
