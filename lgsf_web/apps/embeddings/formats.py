"""
Working out what a document's file is from its bytes.

Every storage key ends ".pdf" (a few old ones ".txt"), whatever the file
is, so the name says nothing. Most files are PDFs. The rest of what's
in data/*/Decisions/documents/ is:

- ModernGov's "Reasons restricted" page, saved in place of a document
  the council hasn't published. 11,439 of these, from 16 councils.
- Other HTML pages saved in place of the document: logon pages, "System
  Information" error pages, councillors' profiles.
- Empty files.
- Word documents (DOCX).
- PDFs wrapped in an HTTP multipart/form-data body (from NTL).
- Emails saved as text (from BUR).
- A ZIP of PDFs (from DEN).

Docling chooses a backend from a file's bytes, and from its extension
when the bytes don't identify it. The extension is always the storage
key's, so text would go to the PDF backend. A file is therefore given to
Docling as a stream named with the extension of the format found here:
see stream_name().
"""

import re
import zipfile
from enum import StrEnum
from pathlib import Path

from embeddings.records import SourceType


class DocumentFormat(StrEnum):
    PDF = "pdf"
    #: A PDF that was saved with the multipart/form-data body it was sent
    #: in. unwrap_multipart() takes the PDF out.
    MULTIPART_PDF = "multipart_pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    #: PNG, JPEG, TIFF or WebP.
    IMAGE = "image"
    #: Plain text, such as an email saved as text. Converted as Markdown.
    TEXT = "text"
    #: Text in a file whose storage key ends ".csv".
    CSV = "csv"
    #: ModernGov's "Reasons restricted" page.
    RESTRICTED = "restricted"
    #: Any other HTML page.
    HTML = "html"
    #: No bytes, or only zero bytes.
    EMPTY = "empty"
    #: Anything else, such as a ZIP that isn't an Office document.
    UNSUPPORTED = "unsupported"


#: The extension a stream of each format that's converted is named with,
#: and so the backend Docling uses for it. Docling recognises an image
#: from its bytes before it looks at the name, so any image extension
#: will do.
EXTENSIONS = {
    DocumentFormat.PDF: "pdf",
    DocumentFormat.MULTIPART_PDF: "pdf",
    DocumentFormat.DOCX: "docx",
    DocumentFormat.XLSX: "xlsx",
    DocumentFormat.PPTX: "pptx",
    DocumentFormat.IMAGE: "png",
    DocumentFormat.TEXT: "md",
    DocumentFormat.CSV: "csv",
}

#: Formats sent to Docling. The others are left out without loading it.
CONVERTED = frozenset(EXTENSIONS)

#: What each converted format's chunks record as their source_type.
SOURCE_TYPES = {
    DocumentFormat.PDF: SourceType.PDF_DOCLING,
    DocumentFormat.MULTIPART_PDF: SourceType.PDF_DOCLING,
    DocumentFormat.DOCX: SourceType.DOCX_DOCLING,
    DocumentFormat.XLSX: SourceType.XLSX_DOCLING,
    DocumentFormat.PPTX: SourceType.PPTX_DOCLING,
    DocumentFormat.IMAGE: SourceType.IMAGE_DOCLING,
    DocumentFormat.TEXT: SourceType.TEXT_DOCLING,
    DocumentFormat.CSV: SourceType.CSV_DOCLING,
}

#: How much of a file is read to tell what it is.
HEAD_SIZE = 8192

_IMAGE_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",  # JPEG
    b"II*\x00",  # TIFF, little-endian
    b"MM\x00*",  # TIFF, big-endian
)

#: The members that tell an Office document from any other ZIP.
_OFFICE_MEMBERS = {
    "word/document.xml": DocumentFormat.DOCX,
    "xl/workbook.xml": DocumentFormat.XLSX,
    "ppt/presentation.xml": DocumentFormat.PPTX,
}

#: The heading of ModernGov's restricted page. Each council's page has
#: its own layout around it, and most have the heading as
#: `<h1>Reasons restricted</h1>` or
#: `<h1  class="mgMainTitleTxt" >Reasons restricted</h1>`. BGE's is an
#: <h2> and TRF's an <h3>.
_RESTRICTED_HEADING = re.compile(
    rb"<h[1-6][^>]*>\s*Reasons restricted", re.IGNORECASE
)

#: Control characters that don't appear in text. Tabs, line breaks and
#: form feeds do.
_BINARY_BYTES = re.compile(rb"[\x00-\x08\x0b\x0e-\x1f\x7f]")


def detect_format(path: Path) -> DocumentFormat:
    with path.open("rb") as f:
        head = f.read(HEAD_SIZE)

    if _is_empty(path, head):
        return DocumentFormat.EMPTY
    if head.startswith(b"%PDF-"):
        return DocumentFormat.PDF
    if _is_multipart_pdf(head):
        return DocumentFormat.MULTIPART_PDF
    if head.startswith(b"PK\x03\x04"):
        return _zip_format(path)
    if head.startswith(_IMAGE_SIGNATURES) or (
        head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    ):
        return DocumentFormat.IMAGE
    if _is_html(head):
        if _RESTRICTED_HEADING.search(path.read_bytes()):
            return DocumentFormat.RESTRICTED
        return DocumentFormat.HTML
    if not _BINARY_BYTES.search(head):
        if path.suffix.lower() == ".csv":
            return DocumentFormat.CSV
        return DocumentFormat.TEXT
    return DocumentFormat.UNSUPPORTED


def _is_empty(path: Path, head: bytes) -> bool:
    if head.strip(b"\x00"):
        return False
    # The first HEAD_SIZE bytes are zero. Check the rest, a block at a time.
    with path.open("rb") as f:
        while block := f.read(1024 * 1024):
            if block.strip(b"\x00"):
                return False
    return True


def _is_multipart_pdf(head: bytes) -> bool:
    """
    The body starts with a boundary line, then the part's headers, then a
    blank line before the PDF:

        --EUx9zqaqn2TsxFgBzOaJzS6z_2kK5ELVkgBcO2R
        Content-Disposition: form-data; name="data"; filename="....pdf"
        Content-Type: application/octet-stream
        Content-Transfer-Encoding: binary

        %PDF-1.5
    """
    if not head.startswith(b"--"):
        return False
    headers, separator, body = head.partition(b"\r\n\r\n")
    return (
        bool(separator)
        and b"content-disposition: form-data" in headers.lower()
        and body.startswith(b"%PDF-")
    )


def unwrap_multipart(data: bytes) -> bytes:
    """The first part of a multipart/form-data body."""
    boundary, _, rest = data.partition(b"\r\n")
    _, separator, rest = rest.partition(b"\r\n\r\n")
    if not boundary.startswith(b"--") or not separator:
        raise ValueError("Not a multipart body")
    part, separator, _ = rest.partition(b"\r\n" + boundary)
    if not separator:
        raise ValueError("The multipart body has no closing boundary")
    return part


def _zip_format(path: Path) -> DocumentFormat:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return DocumentFormat.UNSUPPORTED
    for member, document_format in _OFFICE_MEMBERS.items():
        if member in names:
            return document_format
    return DocumentFormat.UNSUPPORTED


def _is_html(head: bytes) -> bool:
    start = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return start.startswith((b"<!doctype html", b"<html")) or (
        b"<html" in head[:1024].lower()
    )


def stream_name(storage_key: str, document_format: DocumentFormat) -> str:
    """
    The name a converted file's stream is given: its storage key with the
    extension of its format, such as 2015-12-16-995-s9686.md for a text
    email stored as 2015-12-16-995-s9686.txt.
    """
    return f"{Path(storage_key).stem}.{EXTENSIONS[document_format]}"
