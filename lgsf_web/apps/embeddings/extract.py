"""
Converting documents with Docling.

Docling is only imported in the worker processes, so this module
imports without the embeddings dependency group.
"""

from enum import StrEnum

from embeddings.formats import DocumentFormat


class ExtractStatus(StrEnum):
    """What happened when a file was extracted."""

    # Files sent to Docling. Docling's ConversionStatus has SUCCESS,
    # PARTIAL_SUCCESS and FAILURE. A timeout is reported as
    # PARTIAL_SUCCESS with a timeout error, and is kept separate here.
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"

    # Files recognised from their bytes and left out, without loading
    # Docling. See formats.py.
    RESTRICTED = "restricted"
    NOT_DOCUMENT = "not_document"
    EMPTY = "empty"
    UNSUPPORTED = "unsupported"


#: Statuses with a converted document, to chunk.
EXTRACTED = frozenset({ExtractStatus.OK, ExtractStatus.PARTIAL})

#: Statuses that are only tried again when asked to, so that a file that
#: times out doesn't take up its whole timeout on every run.
FAILURES = frozenset({ExtractStatus.FAILED, ExtractStatus.TIMEOUT})

#: Statuses of files that were left out. They have nothing to chunk.
LEFT_OUT = frozenset(
    {
        ExtractStatus.RESTRICTED,
        ExtractStatus.NOT_DOCUMENT,
        ExtractStatus.EMPTY,
        ExtractStatus.UNSUPPORTED,
    }
)

#: The status of each format that's left out.
LEFT_OUT_FORMATS = {
    DocumentFormat.RESTRICTED: ExtractStatus.RESTRICTED,
    DocumentFormat.HTML: ExtractStatus.NOT_DOCUMENT,
    DocumentFormat.EMPTY: ExtractStatus.EMPTY,
    DocumentFormat.UNSUPPORTED: ExtractStatus.UNSUPPORTED,
}
