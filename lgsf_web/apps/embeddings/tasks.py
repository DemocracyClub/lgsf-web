"""
Units of work for embed_documents: one file, and every Document that
links to it.

A council often links the same file from several decisions, and it's
stored under a different storage key each time. Each copy has the same
content_hash, so the unit of work is (council, content_hash): the file
is extracted, chunked and embedded once, and the results are copied to
every storage key.

A Task carries everything the later steps need, so that nothing after
building the tasks touches the database. That lets a Batch worker run
from a manifest of tasks, without access to the database.
"""

from dataclasses import asdict, dataclass

#: Where a council's documents are, under the data directory or the
#: bucket's data/ prefix.
DOCUMENTS_DIR = "{council}/Decisions/documents"


@dataclass(frozen=True)
class LinkedDecision:
    """The decision a Document is linked from."""

    id: int
    identifier: str
    title: str
    decision_maker: str
    #: ISO date
    date: str | None
    url: str


@dataclass(frozen=True)
class LinkedDocument:
    """One Document: one storage key the file is stored under."""

    id: int
    storage_key: str
    title: str
    url: str
    decision: LinkedDecision


@dataclass
class Task:
    council: str
    council_name: str
    content_hash: str
    content_length: int
    #: Every Document with this council and content_hash, ordered by
    #: (decision date, decision id, storage key). The first is the
    #: primary one.
    documents: list[LinkedDocument]

    @property
    def primary(self) -> LinkedDocument:
        """
        The Document whose storage key the work is done at, and whose
        decision the chunk headers name.
        """
        return self.documents[0]

    @property
    def storage_keys(self) -> list[str]:
        return [document.storage_key for document in self.documents]

    def document_key(self, storage_key: str) -> str:
        """Where a storage key's file is, relative to the data directory."""
        directory = DOCUMENTS_DIR.format(council=self.council)
        return f"{directory}/{storage_key}"

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        data = dict(data)
        data["documents"] = [
            LinkedDocument(
                **{
                    **document,
                    "decision": LinkedDecision(**document["decision"]),
                }
            )
            for document in data["documents"]
        ]
        return cls(**data)
