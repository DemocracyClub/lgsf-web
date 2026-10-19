"""
The files embed_documents writes next to each document, and the rules
for which stages a document needs.

For data/MAN/Decisions/documents/2026-08-06-1172-s65106.pdf:

    2026-08-06-1172-s65106.pdf.docling.json   the DoclingDocument
    2026-08-06-1172-s65106.pdf.md             its text, as Markdown
    2026-08-06-1172-s65106.pdf.chunks.jsonl   one Chunk a line
    2026-08-06-1172-s65106.pdf.titan-v2.jsonl one EmbeddingRecord a line,
                                              named after the embedder
    2026-08-06-1172-s65106.pdf.status.json    what has been done

status.json is written last, and records each stage's result. A file
with no entry for its stage in status.json is ignored, and made again.
That's how a run that's stopped part way through is picked up: there's
no log, as S3 can't append to one, and many workers write at once.

The unit of work is a file and every storage key it's stored under (see
tasks.py). The work is done at the primary key, and the files are then
copied to each of the others, so every Document has its own set.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from embeddings.chunking import inputs_hash
from embeddings.extract import EXTRACTED, FAILURES, LEFT_OUT, ExtractStatus
from embeddings.formats import DocumentFormat
from embeddings.tasks import DOCUMENTS_DIR, Task


class Stage(StrEnum):
    EXTRACT = "extract"
    CHUNK = "chunk"
    EMBED = "embed"


class Sidecar(StrEnum):
    """The suffix each sidecar file adds to its document's key."""

    STATUS = "status.json"
    DOCLING = "docling.json"
    TEXT = "md"
    CHUNKS = "chunks.jsonl"


def sidecar_key(document_key: str, suffix: str) -> str:
    return f"{document_key}.{suffix}"


def embeddings_suffix(embedder_name: str) -> str:
    """The suffix of an embedder's file, such as "titan-v2.jsonl"."""
    return f"{embedder_name}.jsonl"


@dataclass
class ExtractEntry:
    status: ExtractStatus
    pages: int | None = None
    seconds: float | None = None
    error: str | None = None
    docling_version: str | None = None
    #: "cpu" or "cuda". None if Docling wasn't loaded.
    device: str | None = None
    #: ISO date and time, in UTC.
    finished_at: str | None = None


@dataclass
class ChunkEntry:
    #: chunking.inputs_hash() of what the chunks were made from. None if
    #: chunking failed.
    inputs_hash: str | None
    max_words: int
    chunks: int = 0
    #: How many chunks have embed=True.
    embeddable: int = 0
    error: str | None = None


@dataclass
class EmbedEntry:
    model: str
    #: The chunk inputs_hash of the chunks that were embedded.
    chunk_inputs_hash: str | None
    #: How many chunks were sent to the model this time.
    embedded: int = 0
    #: How many chunks' embeddings were kept from before.
    reused: int = 0
    tokens: int = 0
    error: str | None = None


@dataclass
class DocumentStatus:
    content_hash: str
    #: Every storage key the file is stored under.
    storage_keys: list[str]
    format: DocumentFormat | None = None
    extract: ExtractEntry | None = None
    chunk: ChunkEntry | None = None
    #: By embedder name.
    embed: dict[str, EmbedEntry] = field(default_factory=dict)

    @property
    def extracted(self) -> bool:
        """Whether there's a converted document to chunk."""
        return self.extract is not None and self.extract.status in EXTRACTED

    @property
    def done_extracting(self) -> bool:
        """Whether extracting again would get the same result."""
        return self.extract is not None and (
            self.extract.status in EXTRACTED or self.extract.status in LEFT_OUT
        )

    @property
    def chunked(self) -> bool:
        return (
            self.extracted
            and self.chunk is not None
            and self.chunk.error is None
            and self.chunk.inputs_hash is not None
        )

    def chunk_inputs_hash(self, task: Task) -> str | None:
        """What inputs_hash() is for this document now, if it's extracted."""
        if not self.extracted:
            return None
        return inputs_hash(task, self.format, self.extract.docling_version)

    def embedded(self, embedder_name: str) -> bool:
        entry = self.embed.get(embedder_name)
        return (
            self.chunked
            and entry is not None
            and entry.error is None
            and entry.chunk_inputs_hash == self.chunk.inputs_hash
        )

    def sidecars(self) -> list[str]:
        """
        The suffixes of the files this status says are complete, apart
        from status.json itself.
        """
        suffixes = []
        if self.extracted:
            suffixes += [Sidecar.DOCLING, Sidecar.TEXT]
        if self.chunked:
            suffixes.append(Sidecar.CHUNKS)
            suffixes += [
                embeddings_suffix(name)
                for name in sorted(self.embed)
                if self.embedded(name)
            ]
        return suffixes

    def as_dict(self) -> dict:
        return asdict(self)

    def as_json(self) -> bytes:
        return json.dumps(
            self.as_dict(), indent=2, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentStatus":
        data = dict(data)
        if data.get("format"):
            data["format"] = DocumentFormat(data["format"])
        if data.get("extract"):
            extract = dict(data["extract"])
            extract["status"] = ExtractStatus(extract["status"])
            data["extract"] = ExtractEntry(**extract)
        if data.get("chunk"):
            data["chunk"] = ChunkEntry(**data["chunk"])
        data["embed"] = {
            name: EmbedEntry(**entry)
            for name, entry in (data.get("embed") or {}).items()
        }
        return cls(**data)

    @classmethod
    def from_json(cls, data: bytes) -> "DocumentStatus":
        return cls.from_dict(json.loads(data))


def read_status(store, document_key: str) -> DocumentStatus | None:
    """
    A document's status, or None if it has none. One that can't be read
    is treated as missing, so the document is done again.
    """
    try:
        data = store.read_bytes(sidecar_key(document_key, Sidecar.STATUS))
    except FileNotFoundError:
        return None
    try:
        return DocumentStatus.from_json(data)
    except (ValueError, KeyError, TypeError):
        return None


def write_status(store, document_key: str, status: DocumentStatus):
    store.write_bytes(
        sidecar_key(document_key, Sidecar.STATUS), status.as_json()
    )


def read_statuses(
    store, tasks: list[Task], threads: int = 16
) -> dict[tuple[str, str], DocumentStatus | None]:
    """
    The status at every storage key of every task, by (council, storage
    key). A status for another content_hash is for a file the council
    has since replaced, and counts as None.

    Each council's documents directory is listed first, so only the
    status files that exist are read. On S3, that's one ListObjectsV2
    for each thousand keys, rather than a request for each document.
    """
    existing = set()
    for council in sorted({task.council for task in tasks}):
        directory = DOCUMENTS_DIR.format(council=council)
        existing.update(store.list_prefix(f"{directory}/"))

    wanted = []
    for task in tasks:
        for storage_key in task.storage_keys:
            document_key = task.document_key(storage_key)
            if sidecar_key(document_key, Sidecar.STATUS) in existing:
                wanted.append((task, storage_key, document_key))

    def read(item):
        task, storage_key, document_key = item
        status = read_status(store, document_key)
        if status is not None and status.content_hash != task.content_hash:
            status = None
        return (task.council, storage_key), status

    statuses = {
        (task.council, storage_key): None
        for task in tasks
        for storage_key in task.storage_keys
    }
    with ThreadPoolExecutor(max_workers=threads) as pool:
        statuses.update(pool.map(read, wanted))
    return statuses


# The rules for each stage


def needs_extract(
    status: DocumentStatus | None, retry_failed=False, force=False
) -> bool:
    """
    A file that was extracted, partly extracted or left out isn't tried
    again unless `force`. One that failed or timed out is only tried
    again with `retry_failed`.
    """
    if force or status is None or status.extract is None:
        return True
    if status.extract.status in FAILURES:
        return retry_failed
    return False


def needs_chunk(
    status: DocumentStatus | None, chunk_inputs_hash: str | None, force=False
) -> bool:
    """
    A converted document is chunked if it hasn't been, if chunking it
    failed, or if what its chunks are made from has changed.
    """
    if status is None or not status.extracted:
        return False
    if force:
        return True
    return not status.chunked or status.chunk.inputs_hash != chunk_inputs_hash


def needs_embed(
    status: DocumentStatus | None, embedder_name: str, force=False
) -> bool:
    """
    Chunks are embedded by a model if they haven't been, if embedding
    them failed, or if they've changed since.
    """
    if status is None or not status.chunked:
        return False
    return force or not status.embedded(embedder_name)


@dataclass
class TaskPlan:
    """What a task needs, found from the statuses at its storage keys."""

    task: Task
    #: The status at each of the task's storage keys, as read.
    statuses: dict[str, DocumentStatus | None]
    #: The status the work starts from: the primary key's, or that of
    #: the key in `copy_from`.
    status: DocumentStatus | None
    #: Another storage key to copy the sidecars from to the primary key,
    #: rather than extract again.
    copy_from: str | None = None
    extract: bool = False
    #: Chunk the converted document saved before. A task that's
    #: extracted is always chunked afterwards, if the chunk stage is run.
    chunk: bool = False
    #: The embedders to embed with, without chunking first. A task that's
    #: chunked is always embedded afterwards, if the embed stage is run.
    embed: list[str] = field(default_factory=list)

    @property
    def needs_worker(self) -> bool:
        """Whether a worker process has to convert or chunk the file."""
        return self.extract or self.chunk

    def copy_to(self, final_status: DocumentStatus | None) -> list[str]:
        """
        The other storage keys whose status isn't the primary key's final
        one, so need the primary key's files copied to them. With no
        status at the primary key, nothing's been done there to copy.
        """
        if final_status is None:
            return []
        return [
            storage_key
            for storage_key in self.task.storage_keys[1:]
            if self.statuses.get(storage_key) != final_status
        ]

    @property
    def needs_status_update(self) -> bool:
        """
        Whether the status needs writing even if no stage runs: it's
        copied from another key, or the file's storage keys have changed.
        """
        return self.copy_from is not None or (
            self.status is not None
            and self.status.storage_keys != self.task.storage_keys
        )

    def nothing_to_do(self, final_status=None) -> bool:
        final_status = final_status or self.status
        return (
            not self.needs_worker
            and not self.embed
            and not self.needs_status_update
            and not self.copy_to(final_status)
        )


def plan_task(
    task: Task,
    statuses: dict[str, DocumentStatus | None],
    stages,
    embedder_names: list[str],
    retry_failed=False,
    force=False,
) -> TaskPlan:
    """
    Decide what a task needs, from the statuses at its storage keys (by
    storage key, and already checked against its content_hash).

    If the primary key hasn't been extracted but another key has, which
    happens when a decision imported later becomes the earliest to link
    to the file, the sidecars are copied from that key rather than
    extracting again. Then each stage is decided from that status by the
    rules above.
    """
    primary = task.primary.storage_key
    status = statuses.get(primary)
    copy_from = None
    if not force and not (status and status.done_extracting):
        for storage_key in task.storage_keys[1:]:
            other = statuses.get(storage_key)
            if other is not None and other.done_extracting:
                copy_from, status = storage_key, other
                break

    plan = TaskPlan(
        task=task, statuses=statuses, status=status, copy_from=copy_from
    )
    if Stage.EXTRACT in stages and needs_extract(status, retry_failed, force):
        plan.extract = True
        return plan
    if Stage.CHUNK in stages and needs_chunk(
        status, status and status.chunk_inputs_hash(task), force
    ):
        plan.chunk = True
        return plan
    if Stage.EMBED in stages:
        plan.embed = [
            name for name in embedder_names if needs_embed(status, name, force)
        ]
    return plan
