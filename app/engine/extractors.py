"""
File-format text extraction.

The one rule every extractor here follows: preserve exact character content.
This module's job is to get from "bytes on disk" to "a Python string" without
losing or altering a single codepoint along the way — a hidden zero-width
character or blank glyph has to survive extraction just as faithfully as the
word it's sitting next to, or the whole point of scanning the file is lost.

Supported formats and what "extraction" means for each:

  .txt          Direct decode. No transformation.
  .html / .htm  Raw markup passthrough — deliberately NOT tag-stripped.
                A hidden character sitting in an attribute or between tags
                is still exactly where it was; stripping tags to get
                "visible text" would silently throw those away.
  .docx         Unzipped and parsed as XML via the standard library only
                (zipfile + ElementTree). Text lives in <w:t> run elements
                as literal XML text content, so nothing is transcoded.
  .pdf          Extracted via pypdf's text layer. Fidelity here depends on
                the PDF's embedded font/ToUnicode data, which is a property
                of the source file, not this code — most PDFs exported from
                Word, browsers, or LLM chat clients embed this correctly.
                Scanned/image-only PDFs have no text layer at all; that's
                an OCR problem, explicitly out of scope for this tool.
  .doc          Not supported. The legacy binary format (OLE compound file
                + piece-table text reconstruction) has no reliable
                pure-Python parser, and a half-correct extractor would
                silently produce wrong results — worse than refusing.
"""

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from typing import List

from pypdf import PdfReader
from pypdf.errors import PdfReadError

SUPPORTED_EXTENSIONS = {"txt", "html", "htm", "docx", "pdf"}

_DOCX_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class ExtractionOutcome:
    text: str
    source_type: str
    warnings: List[str] = field(default_factory=list)


class UnsupportedFileTypeError(Exception):
    def __init__(self, extension: str, message: str):
        self.extension = extension
        self.message = message
        super().__init__(message)


class ExtractionError(Exception):
    pass


def extract_text(filename: str, content: bytes) -> ExtractionOutcome:
    """Dispatch to the correct extractor based on file extension."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if extension == "txt":
        return _extract_txt(content)
    if extension in ("html", "htm"):
        return _extract_html(content)
    if extension == "docx":
        return _extract_docx(content)
    if extension == "pdf":
        return _extract_pdf(content)
    if extension == "doc":
        raise UnsupportedFileTypeError(
            extension,
            "Legacy .doc (pre-2007 binary Word format) isn't supported for reliable text extraction. "
            "Please re-save the file as .docx or .txt and upload again.",
        )

    raise UnsupportedFileTypeError(
        extension or "unknown",
        f"Unsupported file type '.{extension}'. Supported formats: "
        + ", ".join(sorted(SUPPORTED_EXTENSIONS)) + ".",
    )


def _decode_bytes(content: bytes) -> tuple[str, List[str]]:
    """Best-effort decode: UTF-8 first, then a fallback that never raises."""
    warnings: List[str] = []
    try:
        return content.decode("utf-8"), warnings
    except UnicodeDecodeError:
        warnings.append("File was not valid UTF-8; decoded with Latin-1 fallback, which may misrepresent some characters.")
        return content.decode("latin-1"), warnings


def _extract_txt(content: bytes) -> ExtractionOutcome:
    text, warnings = _decode_bytes(content)
    return ExtractionOutcome(text=text, source_type="txt", warnings=warnings)


def _extract_html(content: bytes) -> ExtractionOutcome:
    # Deliberately not parsed/stripped — see module docstring.
    text, warnings = _decode_bytes(content)
    return ExtractionOutcome(text=text, source_type="html", warnings=warnings)


def _extract_docx(content: bytes) -> ExtractionOutcome:
    warnings: List[str] = []
    text_parts: List[str] = []

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            # word/document.xml holds the main body; headers/footers/footnotes
            # are separate parts and are included too, since a hidden
            # signature could just as easily be planted in a footer.
            part_names = [
                name for name in archive.namelist()
                if name.startswith("word/") and name.endswith(".xml")
                and any(part in name for part in ("document", "header", "footer", "footnote", "endnote"))
            ]

            if "word/document.xml" not in part_names:
                raise ExtractionError("This .docx file doesn't contain a readable word/document.xml part.")

            for part_name in part_names:
                xml_bytes = archive.read(part_name)
                text_parts.append(_docx_xml_to_text(xml_bytes))

    except zipfile.BadZipFile as exc:
        raise ExtractionError("File does not appear to be a valid .docx archive.") from exc

    combined = "\n".join(part for part in text_parts if part)
    if not combined.strip():
        warnings.append("No extractable text was found in this document (it may be empty or contain only images/objects).")

    return ExtractionOutcome(text=combined, source_type="docx", warnings=warnings)


def _docx_xml_to_text(xml_bytes: bytes) -> str:
    """
    Walk a WordprocessingML XML part and reconstruct text, preserving every
    literal character inside <w:t> runs exactly as stored. Paragraphs are
    iterated directly (rather than a single flat walk) so paragraph breaks
    land in the right place; tabs and explicit line breaks within a
    paragraph are reintroduced too. Nothing inside a run's text content is
    ever altered — including any hidden characters it contains.
    """
    root = ET.fromstring(xml_bytes)
    lines: List[str] = []

    for para in root.iter(f"{_DOCX_WORD_NS}p"):
        para_parts: List[str] = []
        for node in para.iter():
            if node.tag == f"{_DOCX_WORD_NS}t":
                para_parts.append(node.text or "")
            elif node.tag == f"{_DOCX_WORD_NS}tab":
                para_parts.append("\t")
            elif node.tag in (f"{_DOCX_WORD_NS}br", f"{_DOCX_WORD_NS}cr"):
                para_parts.append("\n")
        lines.append("".join(para_parts))

    return "\n".join(lines)


def _pdf_has_font_without_unicode_mapping(reader: PdfReader) -> bool:
    """
    Checks whether any font embedded in the PDF lacks a /ToUnicode CMap.

    This matters specifically for hidden-character detection: a PDF built
    with a simple 8-bit font (WinAnsi/StandardEncoding, no ToUnicode) can
    represent standard Latin text just fine — pypdf recovers that via the
    font's base encoding table — but has no reliable way to carry a
    codepoint outside that encoding, including zero-width or other
    invisible Unicode characters. If such a character was present in the
    original source, it may never have survived being embedded into the
    PDF in the first place, or may not be recoverable from the content
    stream with certainty. This is a property of how the PDF was produced,
    not something any extractor can compensate for after the fact.
    """
    try:
        for page in reader.pages:
            resources = page.get("/Resources")
            if not resources:
                continue
            fonts = resources.get("/Font")
            if not fonts:
                continue
            for font_ref in fonts.get_object().values():
                font_obj = font_ref.get_object()
                if "/ToUnicode" not in font_obj:
                    return True
    except Exception:
        # Diagnostic best-effort only — never let this check break extraction.
        return False
    return False


def _extract_pdf(content: bytes) -> ExtractionOutcome:
    warnings: List[str] = []

    try:
        reader = PdfReader(io.BytesIO(content))
    except PdfReadError as exc:
        raise ExtractionError("File does not appear to be a valid PDF.") from exc

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ExtractionError("This PDF is password-protected; remove the password and re-upload.")

    pages_text: List[str] = []
    empty_pages = 0
    for i, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if not page_text.strip():
            empty_pages += 1
        pages_text.append(page_text)

    if _pdf_has_font_without_unicode_mapping(reader):
        warnings.append(
            "One or more fonts in this PDF have no Unicode mapping data (ToUnicode CMap). Standard Latin text "
            "extracts reliably regardless, but characters outside standard Latin script — including hidden "
            "Unicode signatures — may not survive extraction with certainty. If you suspect hidden characters "
            "in this file, re-export it from its original source (e.g. a word processor or browser's Print to "
            "PDF) and re-scan."
        )

    warnings.append(
        "PDF limitation: zero-width and bidi-control characters (ZWSP, ZWJ, word joiner, RLO/LRO) are commonly "
        "dropped during PDF text-shaping regardless of which tool generated the file, even when their visual "
        "effect remains on the page. Non-breaking/exotic spacing characters are unaffected. For full confidence "
        "on zero-width or bidi characters, scan the original source document instead of an exported PDF."
    )

    if empty_pages == len(pages_text) and pages_text:
        warnings.append(
            "No extractable text layer was found on any page — this PDF may be scanned/image-based. "
            "This tool does not perform OCR."
        )
    elif empty_pages:
        warnings.append(f"{empty_pages} of {len(pages_text)} page(s) had no extractable text.")

    return ExtractionOutcome(text="\n".join(pages_text), source_type="pdf", warnings=warnings)
