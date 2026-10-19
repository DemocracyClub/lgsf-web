"""
Running the stages for each task.

A task that needs extracting or chunking goes to a worker process,
which reads the file, converts it, chunks it and writes the
docling.json, .md and chunks.jsonl sidecars at the primary storage key.
It hands the chunks back to the parent process, which embeds them,
writes the embeddings and status.json, and copies the files to the
task's other storage keys. Only the parent writes status.json.

A task that only needs embedding, or copying, is done by the parent.

An error while chunking or embedding one task is recorded in its
status, and the run carries on. The next run tries it again.
"""

import datetime
import hashlib
import json
import tempfile
import time
import traceback
from collections.abc import Callable, Sequence
from concurrent.futures import as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path

from embeddings import extract
from embeddings.chunking import MAX_WORDS, chunk_document, inputs_hash
from embeddings.embedders import EmbedderBase
from embeddings.extract import (
    EXTRACTED,
    LEFT_OUT_FORMATS,
    ExtractStatus,
)
from embeddings.formats import DocumentFormat, detect_format
from embeddings.records import Chunk, EmbeddingRecord, embed_chunks
from embeddings.sidecars import (
    ChunkEntry,
    DocumentStatus,
    EmbedEntry,
    ExtractEntry,
    Sidecar,
    Stage,
    TaskPlan,
    embeddings_suffix,
    list_keys,
    needs_embed,
    plan_task,
    read_statuses,
    sidecar_key,
    write_status,
)
from embeddings.tasks import Task

#: Formats whose pages are counted for --max-pages.
PDF_FORMATS = (DocumentFormat.PDF, DocumentFormat.MULTIPART_PDF)


@dataclass
class WorkResult:
    """What a worker hands back to the parent for one task."""

    format: DocumentFormat | None = None
    #: Set if the file was extracted this time.
    extract: ExtractEntry | None = None
    #: Set if the document was chunked this time.
    chunk: ChunkEntry | None = None
    chunks: list[Chunk] | None = None
    #: The file isn't in the store. Nothing is recorded, so it's looked
    #: for again next time.
    missing: bool = False
    #: The PDF has more pages than --max-pages. Nothing is recorded, so a
    #: later run picks it up.
    too_long: int | None = None


@dataclass
class Options:
    stages: Sequence[Stage]
    max_pages: int | None = None
    force: bool = False


@dataclass
class TaskOutcome:
    """What happened to one task, for the parent to report."""

    plan: TaskPlan
    status: DocumentStatus | None = None
    result: WorkResult = field(default_factory=WorkResult)
    #: The embedders that embedded the chunks this time.
    embedded_with: list[str] = field(default_factory=list)
    #: The other storage keys the files were copied to.
    copied_to: list[str] = field(default_factory=list)
    #: An error that stopped the task before its status was written.
    error: str | None = None
    seconds: float = 0.0


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


# In a worker process


def work(
    task: Task,
    status: DocumentStatus | None,
    do_extract: bool,
    store,
    options: Options,
) -> WorkResult:
    """
    Extract a task's file if `do_extract`, then chunk it if the chunk
    stage is run and there's a converted document: the one just made, or
    the one saved before.
    """
    result = WorkResult(format=status.format if status else None)
    document = None
    if do_extract:
        result, document = _extract(task, store, options)
        if result.missing or result.too_long:
            return result
        extracted = result.extract.status in EXTRACTED
    else:
        extracted = status is not None and status.extracted

    if Stage.CHUNK in options.stages and extracted:
        docling_version = (
            result.extract.docling_version
            if result.extract
            else status.extract.docling_version
        )
        result.chunk, result.chunks = _chunk(
            task, document, result.format, docling_version, store
        )
    return result


def _extract(task: Task, store, options: Options):
    """Returns the WorkResult, and the DoclingDocument if there is one."""
    start = time.monotonic()
    primary_key = task.document_key(task.primary.storage_key)

    def entry(status, **fields):
        return ExtractEntry(
            status=status,
            seconds=round(time.monotonic() - start, 1),
            finished_at=_now(),
            **fields,
        )

    with tempfile.TemporaryDirectory() as directory:
        try:
            path = store.download_to(primary_key, Path(directory))
        except FileNotFoundError:
            return WorkResult(missing=True), None

        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != task.content_hash:
            return WorkResult(
                extract=entry(
                    ExtractStatus.FAILED,
                    error=f"The file's hash is {digest}, not the "
                    f"{task.content_hash} its Documents have",
                )
            ), None

        document_format = detect_format(path)
        result = WorkResult(format=document_format)
        if document_format in LEFT_OUT_FORMATS:
            result.extract = entry(LEFT_OUT_FORMATS[document_format])
            return result, None

        try:
            data = extract.document_bytes(path, document_format)
            if document_format in PDF_FORMATS and options.max_pages:
                pages = extract.count_pages(data)
                if pages is not None and pages > options.max_pages:
                    return WorkResult(too_long=pages), None
            conversion = extract.convert(
                extract.document_stream(
                    data, task.primary.storage_key, document_format
                )
            )
            if conversion.document is not None:
                store.write_bytes(
                    sidecar_key(primary_key, Sidecar.DOCLING),
                    extract.docling_json(conversion.document),
                )
                store.write_bytes(
                    sidecar_key(primary_key, Sidecar.TEXT),
                    conversion.document.export_to_markdown().encode("utf-8"),
                )
        except Exception as exc:  # noqa: BLE001
            # Anything Docling raises, recorded for this file alone.
            result.extract = entry(
                ExtractStatus.FAILED,
                error=_error(exc),
                docling_version=extract.docling_version(),
                device=extract.converter_device(),
            )
            return result, None

        result.extract = entry(
            conversion.status,
            pages=conversion.pages,
            error=conversion.error,
            docling_version=extract.docling_version(),
            device=extract.converter_device(),
        )
        return result, conversion.document


def _chunk(task, document, document_format, docling_version, store):
    """Returns the ChunkEntry, and the chunks if chunking succeeded."""
    primary_key = task.document_key(task.primary.storage_key)
    try:
        if document is None:
            document = extract.load_docling_json(
                store.read_bytes(sidecar_key(primary_key, Sidecar.DOCLING))
            )
        chunks = chunk_document(task, document, document_format)
        store.write_bytes(
            sidecar_key(primary_key, Sidecar.CHUNKS),
            "".join(f"{chunk.as_json()}\n" for chunk in chunks).encode("utf-8"),
        )
    except Exception as exc:  # noqa: BLE001
        # An unreadable docling.json, or anything docling-core raises.
        return ChunkEntry(
            inputs_hash=None, max_words=MAX_WORDS, error=_error(exc)
        ), None
    return (
        ChunkEntry(
            inputs_hash=inputs_hash(task, document_format, docling_version),
            max_words=MAX_WORDS,
            chunks=len(chunks),
            embeddable=sum(chunk.embed for chunk in chunks),
        ),
        chunks,
    )


# In the parent process


def plan_tasks(
    tasks: Sequence[Task],
    store,
    stages: Sequence[Stage],
    embedder_names: Sequence[str],
    retry_failed=False,
    force=False,
) -> tuple[list[TaskPlan], set[str]]:
    """
    A plan for each task, from the statuses at its storage keys, and
    every key in the councils' documents directories.
    """
    existing = list_keys(store, tasks)
    statuses = read_statuses(store, tasks, existing)
    plans = [
        plan_task(
            task,
            {key: statuses[(task.council, key)] for key in task.storage_keys},
            stages,
            list(embedder_names),
            retry_failed=retry_failed,
            force=force,
        )
        for task in tasks
    ]
    return plans, existing


def prepare(plan: TaskPlan, store):
    """
    Copy the sidecars from another storage key to the primary key, if the
    plan says to. status.json isn't copied: the primary key's is written
    when the task is finished.
    """
    if plan.copy_from is None:
        return
    task = plan.task
    source = task.document_key(plan.copy_from)
    target = task.document_key(task.primary.storage_key)
    for suffix in plan.status.sidecars():
        store.copy(sidecar_key(source, suffix), sidecar_key(target, suffix))


def finish(
    plan: TaskPlan,
    result: WorkResult,
    store,
    embedders: Sequence[EmbedderBase],
    options: Options,
) -> TaskOutcome:
    """
    Embed the chunks, write the primary key's status.json, and copy the
    files to every other storage key whose status isn't the same.
    """
    task = plan.task
    outcome = TaskOutcome(plan=plan, result=result)
    if result.missing or result.too_long:
        return outcome

    if plan.status is not None:
        status = replace(plan.status, embed=dict(plan.status.embed))
    else:
        status = DocumentStatus(
            content_hash=task.content_hash, storage_keys=task.storage_keys
        )
    status.storage_keys = task.storage_keys
    if result.extract is not None:
        # A new extraction: what was chunked and embedded before is of
        # the old one.
        status.format = result.format
        status.extract = result.extract
        status.chunk = None
        status.embed = {}
    if result.chunk is not None:
        status.chunk = result.chunk

    if Stage.EMBED in options.stages:
        chunks = result.chunks
        for embedder in embedders:
            rechunked = result.chunk is not None and status.chunked
            if not (
                rechunked or needs_embed(status, embedder.name, options.force)
            ):
                continue
            if chunks is None:
                chunks = _read_chunks(store, task)
            status.embed[embedder.name] = _embed(
                task, status, chunks, embedder, store, options.force
            )
            outcome.embedded_with.append(embedder.name)

    primary_key = task.document_key(task.primary.storage_key)
    write_status(store, primary_key, status)
    outcome.status = status
    outcome.copied_to = plan.copy_to(status)
    for storage_key in outcome.copied_to:
        target = task.document_key(storage_key)
        for suffix in status.sidecars():
            store.copy(
                sidecar_key(primary_key, suffix), sidecar_key(target, suffix)
            )
        write_status(store, target, status)
    return outcome


def _read_chunks(store, task: Task) -> list[Chunk]:
    key = sidecar_key(
        task.document_key(task.primary.storage_key), Sidecar.CHUNKS
    )
    return [
        Chunk.from_dict(json.loads(line))
        for line in store.read_bytes(key).decode("utf-8").splitlines()
        if line.strip()
    ]


def _read_embeddings(store, key: str) -> dict[str, EmbeddingRecord]:
    """
    The embeddings file written before, if there is one. It's read even
    without a status entry: embed_chunks() only reuses a record made from
    the same text by the same model, so a record is either right or not
    used.
    """
    try:
        data = store.read_bytes(key)
    except FileNotFoundError:
        return {}
    try:
        records = [
            EmbeddingRecord.from_dict(json.loads(line))
            for line in data.decode("utf-8").splitlines()
            if line.strip()
        ]
    except (ValueError, TypeError):
        return {}
    return {record.chunk_id: record for record in records}


def _embed(task, status, chunks, embedder, store, force) -> EmbedEntry:
    key = sidecar_key(
        task.document_key(task.primary.storage_key),
        embeddings_suffix(embedder.name),
    )
    try:
        existing = {} if force else _read_embeddings(store, key)
        records, embedded = embed_chunks(chunks, embedder, existing)
        store.write_bytes(
            key,
            "".join(f"{record.as_json()}\n" for record in records).encode(
                "utf-8"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        # Such as a Bedrock ThrottlingException that outlasts the client's
        # retries. Without this, one throttle would end a Batch shard.
        return EmbedEntry(
            model=embedder.model,
            chunk_inputs_hash=status.chunk.inputs_hash,
            error=_error(exc),
        )
    # A reused record is the one read from the file.
    sent = [r for r in records if existing.get(r.chunk_id) is not r]
    return EmbedEntry(
        model=embedder.model,
        chunk_inputs_hash=status.chunk.inputs_hash,
        embedded=embedded,
        reused=len(records) - embedded,
        # The tokens the model read this time.
        tokens=sum(record.token_count for record in sent),
    )


def run(
    plans: Sequence[TaskPlan],
    store,
    embedders: Sequence[EmbedderBase],
    options: Options,
    executor,
    on_outcome: Callable[[TaskOutcome], None] | None = None,
):
    """
    Do the work each plan needs. Tasks that need a worker are submitted
    to `executor` smallest first, so the largest run last and a problem
    with one of them doesn't hold up the rest. While they run, the parent
    does the tasks that don't need one.
    """
    to_work = sorted(
        (plan for plan in plans if plan.needs_worker),
        key=lambda plan: plan.task.content_length,
    )
    futures = {}
    try:
        for plan in to_work:
            prepare(plan, store)
            future = executor.submit(
                work, plan.task, plan.status, plan.extract, store, options
            )
            futures[future] = (plan, time.monotonic())

        for plan in plans:
            if plan.needs_worker or plan.nothing_to_do():
                continue
            start = time.monotonic()
            prepare(plan, store)
            outcome = _finish_safely(
                plan, WorkResult(), store, embedders, options
            )
            outcome.seconds = round(time.monotonic() - start, 1)
            if on_outcome:
                on_outcome(outcome)

        for future in as_completed(futures):
            plan, start = futures[future]
            try:
                result = future.result()
            except Exception:  # noqa: BLE001
                # A worker raised something work() didn't catch. Nothing is
                # recorded, so the task is tried again next time.
                outcome = TaskOutcome(plan=plan, error=traceback.format_exc())
            else:
                outcome = _finish_safely(
                    plan, result, store, embedders, options
                )
            outcome.seconds = round(time.monotonic() - start, 1)
            if on_outcome:
                on_outcome(outcome)
    except BaseException:
        # Stopped, or a worker died. What's been written is kept, and the
        # rest is done by the next run.
        if futures:
            executor.shutdown(wait=False, cancel_futures=True)
        raise


def _finish_safely(plan, result, store, embedders, options) -> TaskOutcome:
    """
    finish(), with an error writing to the store reported for that task
    alone, rather than ending the run.
    """
    try:
        return finish(plan, result, store, embedders, options)
    except Exception:  # noqa: BLE001
        return TaskOutcome(
            plan=plan, result=result, error=traceback.format_exc()
        )
