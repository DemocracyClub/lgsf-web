"""
Turning a converted document into Chunks.

Each chunk's header names the council, the primary Document's decision,
the document and the section the chunk is from. Its metadata lists
every decision linking to the file.
"""

import datetime
import hashlib
import json
import re

from embeddings.formats import SOURCE_TYPES, DocumentFormat
from embeddings.records import Chunk, ChunkType
from embeddings.tasks import Task

#: Change this when a change to the code here, to documents.py, or to
#: the docling-core version changes the chunks that are made. Every
#: document is then chunked again, and every chunk whose text changed
#: is embedded again. Extraction isn't repeated.
CHUNKER_VERSION = 1

#: The most words in a chunk. Words for now, until an embedding model's
#: tokenizer is used.
MAX_WORDS = 350

#: Chunks with fewer words than this aren't embedded. They're mostly a
#: line on its own, such as "Made by an Executive Member or Chief
#: Officer".
MIN_EMBED_WORDS = 15

#: The date of the meeting a decision was taken at, in front of its
#: decision maker: "12/01/2026 - Cabinet".
_MEETING_DATE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{4}\s*-\s*")


def inputs_hash(
    task: Task,
    document_format: DocumentFormat,
    docling_version: str,
    max_words: int = MAX_WORDS,
    min_embed_words: int = MIN_EMBED_WORDS,
) -> str:
    """
    A hash of everything a document's chunks are made from, apart from
    the converted document itself. When it changes, the document is
    chunked again.

    That's the chunking settings and code version, the Docling version
    that converted the document, and the task's metadata: the council
    and every linked Document's title, url and decision. So a decision
    retitled in the database means its documents are chunked again, but
    not converted again.
    """
    inputs = {
        "chunker_version": CHUNKER_VERSION,
        "max_words": max_words,
        "min_embed_words": min_embed_words,
        "docling_version": docling_version,
        "format": str(document_format),
        "council": task.council,
        "council_name": task.council_name,
        "content_hash": task.content_hash,
        "documents": [
            {
                "storage_key": document.storage_key,
                "title": document.title,
                "url": document.url,
                "decision": {
                    "identifier": document.decision.identifier,
                    "title": document.decision.title,
                    "decision_maker": document.decision.decision_maker,
                    "date": document.decision.date,
                    "url": document.decision.url,
                },
            }
            for document in task.documents
        ],
    }
    encoded = json.dumps(inputs, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def chunk_document(
    task: Task,
    document,
    document_format: DocumentFormat,
    max_words: int = MAX_WORDS,
    min_embed_words: int = MIN_EMBED_WORDS,
) -> list[Chunk]:
    """
    Split a DoclingDocument and wrap each part in a Chunk. This needs
    docling-core, from the embeddings dependency group.
    """
    from embeddings.documents import count_words, split_document

    parts = split_document(document, max_words=max_words)
    parent_id = ":".join(
        [
            task.council,
            str(ChunkType.DOCUMENTS),
            task.content_hash.removeprefix("sha256:"),
        ]
    )
    primary = task.primary
    metadata = {
        "url": primary.url,
        "content_hash": task.content_hash,
        "storage_key": primary.storage_key,
        "document_title": primary.title,
        "decisions": _decisions(task),
    }
    return [
        Chunk(
            chunk_id=f"{parent_id}:{index}",
            parent_id=parent_id,
            council=task.council,
            type=ChunkType.DOCUMENTS,
            source_type=SOURCE_TYPES[document_format],
            date=primary.decision.date,
            context=context(task, part.headings),
            text=part.text,
            chunk_index=index,
            chunk_count=len(parts),
            embed=count_words(part.text) >= min_embed_words,
            metadata={
                **metadata,
                "pages": part.pages,
                "headings": part.headings,
            },
        )
        for index, part in enumerate(parts)
    ]


def _decisions(task: Task) -> list[dict]:
    """Every decision linking to the file, earliest first, each once."""
    decisions = []
    seen = set()
    for document in task.documents:
        decision = document.decision
        if decision.id in seen:
            continue
        seen.add(decision.id)
        decisions.append(
            {
                "identifier": decision.identifier,
                "title": decision.title,
                "url": decision.url,
                "date": decision.date,
            }
        )
    return decisions


def context(task: Task, headings: list[str]) -> str:
    """
    The primary decision's header, then the document and section. For
    example:

        Manchester City Council · Strategic Director (Corporate Services) & City Treasurer · 6 August 2026
        Decision: P-1475 Domestic Abuse - Intersecting Needs Safe Accommodation (2026/06/09A)
        D3 P-1475 Domestic Abuse - Intersecting Needs Safe Accommodation · Notice of Decision Made

    A decision taken at a meeting has the meeting's date in front of its
    decision maker, as in "12/01/2026 - Cabinet". That's left out,
    because the header already has the date. The date is written out so
    that a search for "August 2026" matches it.
    """
    primary = task.primary
    decision = primary.decision
    decision_maker = _MEETING_DATE.sub("", decision.decision_maker or "")
    first_line = " · ".join(
        part
        for part in (
            task.council_name,
            decision_maker.strip(),
            _date_in_words(decision.date),
        )
        if part
    )
    title = (decision.title or "").strip()
    second_line = f"Decision: {title}" if title else ""
    document_line = " · ".join(
        part for part in (primary.title.strip(), *headings) if part
    )
    return "\n".join(
        line for line in (first_line, second_line, document_line) if line
    )


def _date_in_words(iso_date: str | None) -> str:
    if not iso_date:
        return ""
    date = datetime.date.fromisoformat(iso_date)
    return f"{date.day} {date:%B %Y}"
