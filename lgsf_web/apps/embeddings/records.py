"""
The records written to a document's chunks and embeddings sidecars, and
deciding which chunks need embedding.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from embeddings.embedders import EmbedderBase


class ChunkType(StrEnum):
    """The kind of council record a chunk's text comes from."""

    #: Documents linked from decisions.
    DOCUMENTS = "documents"


class SourceType(StrEnum):
    """The format the chunk's text was read from."""

    #: A PDF converted by Docling.
    PDF_DOCLING = "pdf_docling"


@dataclass
class Chunk:
    """
    One piece of text to embed, and what's needed to find and filter it.

    A field is at the top level if every chunk has it and it's used to
    identify, filter or embed the chunk. Anything only some sources have,
    or that's only for display, goes in `metadata`. `metadata["url"]` is
    the web page the chunk comes from.
    """

    #: Stable between runs: `{parent_id}:{chunk_index}`.
    chunk_id: str
    #: The source this chunk was cut from, as `{council}:{type}:{...}`.
    #: A field rather than just a prefix of chunk_id because vector stores
    #: filter on fields: it's how all of a source's chunks are found, and
    #: deleted when the source shrinks or disappears.
    parent_id: str
    council: str
    type: ChunkType
    source_type: SourceType
    #: ISO date
    date: str | None
    #: A header naming where the text comes from, put in front of it when
    #: embedding so the chunk can be found by council, committee or date.
    context: str
    text: str
    chunk_index: int = 0
    chunk_count: int = 1
    #: False for chunks not worth creating embeddings for. The chunker
    #: knows its source, so it decides; the embedding step only reads this.
    embed: bool = True
    metadata: dict = field(default_factory=dict)

    @property
    def embed_text(self):
        # A chunk can be the header alone, for a source with nothing more
        # than its title.
        return "\n\n".join(part for part in (self.context, self.text) if part)

    @property
    def text_hash(self):
        """
        Hash of the text that gets embedded, header included, so a change
        to either means the chunk needs embedding again.
        """
        return hashlib.sha256(self.embed_text.encode("utf-8")).hexdigest()

    @property
    def word_count(self):
        return len(self.text.split())

    def as_dict(self):
        out = asdict(self)
        out["type"] = str(self.type)
        out["source_type"] = str(self.source_type)
        # Derived, but written out so a change can be spotted without
        # recomputing from the text.
        out["text_hash"] = self.text_hash
        out["word_count"] = self.word_count
        return out

    def as_json(self):
        return json.dumps(self.as_dict(), sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data.pop("text_hash", None)
        data.pop("word_count", None)
        data["type"] = ChunkType(data["type"])
        data["source_type"] = SourceType(data["source_type"])
        return cls(**data)


@dataclass
class EmbeddingRecord:
    """One chunk's embedding: one line of an embeddings file."""

    chunk_id: str
    #: The chunk's text_hash when it was embedded. If the chunk's hash is
    #: different now, this embedding is of old text.
    text_hash: str
    #: The provider's model ID, so each file says what made it.
    model: str
    token_count: int
    embedding: list[float]

    def as_dict(self):
        return asdict(self)

    def as_json(self):
        return json.dumps(self.as_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


def embed_chunks(
    chunks: Sequence[Chunk],
    embedder: EmbedderBase,
    existing: dict[str, EmbeddingRecord],
) -> tuple[list[EmbeddingRecord], int]:
    """
    Records for every chunk to embed, and how many were newly embedded.

    An existing record is reused if it was made from the same text by the
    same model, at the same size. Everything else is sent to the embedder
    in one call. Records come back in the chunks' order, and only for
    current chunks with embed=True, so records for chunks that have gone
    are dropped.
    """
    records = {}
    to_embed = []
    for chunk in chunks:
        if not chunk.embed:
            continue
        record = existing.get(chunk.chunk_id)
        if (
            record
            and record.text_hash == chunk.text_hash
            and record.model == embedder.model
            and len(record.embedding) == embedder.dimensions
        ):
            records[chunk.chunk_id] = record
        else:
            to_embed.append(chunk)

    if to_embed:
        embeddings = embedder.embed_documents([c.embed_text for c in to_embed])
        for chunk, embedding in zip(to_embed, embeddings, strict=True):
            records[chunk.chunk_id] = EmbeddingRecord(
                chunk_id=chunk.chunk_id,
                text_hash=chunk.text_hash,
                model=embedder.model,
                token_count=embedding.token_count,
                embedding=embedding.vector,
            )

    ordered = [records[c.chunk_id] for c in chunks if c.chunk_id in records]
    return ordered, len(to_embed)
