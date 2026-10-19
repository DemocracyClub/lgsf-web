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

import heapq
import json
from dataclasses import asdict, dataclass
from pathlib import Path

#: Where a council's documents are, under the data directory or the
#: bucket's data/ prefix.
DOCUMENTS_DIR = "{council}/Decisions/documents"

#: A manifest is a directory of these, one for each shard.
SHARD_NAME = "shard-{index:05d}.jsonl"
#: And this, saying what the manifest was made from.
RUN_NAME = "run.json"


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


def build_tasks(documents, limit: int | None = None) -> list[Task]:
    """
    The tasks for a queryset of Documents: one for each (council,
    content_hash) of the Documents.

    The queryset only chooses which files to work on. Each task has
    every Document in the database with its council and content_hash,
    whether or not it's in the queryset, so a task is the same whatever
    filters chose it, and so are the files written for it.

    Tasks are in the order of their primary Documents, and `limit` keeps
    the first that many.
    """
    from core.models import Document
    from django.db.models import F

    chosen = documents.exclude(content_hash="")
    pairs = set(chosen.values_list("decision__council", "content_hash"))
    linked = (
        Document.objects.filter(
            content_hash__in=chosen.values("content_hash"),
            decision__council__in=chosen.values("decision__council"),
        )
        .select_related("decision__council")
        .only(
            "id",
            "storage_key",
            "title",
            "url",
            "content_hash",
            "content_length",
            "decision__id",
            "decision__council__name",
            "decision__raw_identifier",
            "decision__raw_title",
            "decision__raw_decision_maker",
            "decision__raw_date",
            "decision__url",
        )
        .order_by(
            F("decision__raw_date").asc(nulls_last=True),
            "decision__id",
            "storage_key",
        )
    )

    tasks = {}
    for document in linked:
        council = document.decision.council_id
        pair = (council, document.content_hash)
        if pair not in pairs:
            # The same file at another council, or a council with the
            # file under another hash.
            continue
        task = tasks.get(pair)
        if task is None:
            task = tasks[pair] = Task(
                council=council,
                council_name=document.decision.council.name,
                content_hash=document.content_hash,
                content_length=document.content_length or 0,
                documents=[],
            )
        task.documents.append(_linked_document(document))
    ordered = list(tasks.values())
    return ordered[:limit] if limit is not None else ordered


def _linked_document(document) -> LinkedDocument:
    decision = document.decision
    return LinkedDocument(
        id=document.id,
        storage_key=document.storage_key,
        title=document.title,
        url=document.url,
        decision=LinkedDecision(
            id=decision.id,
            identifier=decision.raw_identifier,
            title=decision.raw_title,
            decision_maker=decision.raw_decision_maker,
            date=decision.raw_date.isoformat() if decision.raw_date else None,
            url=decision.url,
        ),
    )


def shard(tasks: list[Task], shards: int) -> list[list[Task]]:
    """
    Split tasks into `shards` lists of about the same total size: each
    task, largest first, goes into the shard with the fewest bytes so
    far. Every shard is returned, even if it's empty.
    """
    heap = [(0, index) for index in range(shards)]
    result = [[] for _ in range(shards)]
    for task in sorted(tasks, key=lambda t: t.content_length, reverse=True):
        size, index = heapq.heappop(heap)
        result[index].append(task)
        heapq.heappush(heap, (size + task.content_length, index))
    return result


def shard_json(tasks: list[Task]) -> bytes:
    return "".join(
        json.dumps(task.as_dict(), ensure_ascii=False) + "\n" for task in tasks
    ).encode("utf-8")


def tasks_from_json(data: bytes) -> list[Task]:
    return [
        Task.from_dict(json.loads(line))
        for line in data.decode("utf-8").splitlines()
        if line.strip()
    ]


def write_manifest(
    directory: Path, shards: list[list[Task]], run: dict
) -> list[Path]:
    """Write a shard file for each list of tasks, and run.json."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, tasks in enumerate(shards):
        path = directory / SHARD_NAME.format(index=index)
        path.write_bytes(shard_json(tasks))
        paths.append(path)
    (directory / RUN_NAME).write_text(json.dumps(run, indent=2) + "\n")
    return paths


def read_manifest(location: str, index: int = 0) -> list[Task]:
    """
    One shard's tasks from a manifest: a local directory, or an
    s3://bucket/prefix/ URL.
    """
    name = SHARD_NAME.format(index=index)
    if location.startswith("s3://"):
        import boto3

        bucket, _, prefix = location.removeprefix("s3://").partition("/")
        key = f"{prefix.rstrip('/')}/{name}" if prefix else name
        response = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return tasks_from_json(response["Body"].read())
    return tasks_from_json((Path(location) / name).read_bytes())
