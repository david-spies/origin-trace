"""Tests for app.engine.extractors — built against real, minimal files, not mocks."""

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from pypdf import PdfWriter

from app.engine.extractors import ExtractionError, UnsupportedFileTypeError, extract_text
from app.engine.unicode_scanner import UnicodeScanner

_DOCX_DOCUMENT_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{para1}</w:t></w:r></w:p>
    <w:p><w:r><w:t>{para2}</w:t></w:r></w:p>
  </w:body>
</w:document>"""

_DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""


def _build_minimal_docx(para1: str, para2: str = "Second paragraph.") -> bytes:
    """Construct a real, minimally-valid .docx (a zip of OOXML parts) in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        z.writestr("word/document.xml", _DOCX_DOCUMENT_XML_TEMPLATE.format(para1=para1, para2=para2))
    return buf.getvalue()


def _build_minimal_pdf(text: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    # pypdf's writer doesn't expose a high-level "draw text" API, so this
    # PDF intentionally has no text layer — used only to test the
    # empty-text-layer warning path, not character-fidelity extraction.
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------
# .txt
# ---------------------------------------------------------------------

def test_extract_txt_preserves_hidden_characters():
    content = "Hello\u200bWorld".encode("utf-8")
    outcome = extract_text("sample.txt", content)
    assert outcome.text == "Hello\u200bWorld"
    assert outcome.source_type == "txt"
    findings = UnicodeScanner.scan(outcome.text)
    assert len(findings) == 1


def test_extract_txt_falls_back_on_bad_encoding():
    content = b"\xff\xfe not valid utf-8"
    outcome = extract_text("broken.txt", content)
    assert outcome.text  # decoded via latin-1 fallback, not raised
    assert any("fallback" in w.lower() for w in outcome.warnings)


# ---------------------------------------------------------------------
# .html
# ---------------------------------------------------------------------

def test_extract_html_preserves_markup_and_hidden_chars():
    html = '<html><body><p>Hello\u200bWorld</p><!-- \u202e --></body></html>'
    outcome = extract_text("page.html", html.encode("utf-8"))
    assert outcome.source_type == "html"
    assert "<p>" in outcome.text  # markup is NOT stripped
    findings = UnicodeScanner.scan(outcome.text)
    categories = {f.category for f in findings}
    assert "zero_width" in categories
    assert "bidi_control" in categories


# ---------------------------------------------------------------------
# .docx
# ---------------------------------------------------------------------

def test_extract_docx_preserves_hidden_character_in_run():
    docx_bytes = _build_minimal_docx(para1="Secret\u200bMessage")
    outcome = extract_text("sample.docx", docx_bytes)
    assert outcome.source_type == "docx"
    assert "Secret\u200bMessage" in outcome.text
    findings = UnicodeScanner.scan(outcome.text)
    assert any(f.category == "zero_width" for f in findings)


def test_extract_docx_preserves_paragraph_structure():
    docx_bytes = _build_minimal_docx(para1="First paragraph.", para2="Second paragraph.")
    outcome = extract_text("sample.docx", docx_bytes)
    assert "First paragraph." in outcome.text
    assert "Second paragraph." in outcome.text


def test_extract_docx_rejects_bad_zip():
    with pytest.raises(ExtractionError):
        extract_text("fake.docx", b"not a real zip file")


# ---------------------------------------------------------------------
# .pdf
# ---------------------------------------------------------------------

def test_extract_pdf_warns_on_no_text_layer():
    pdf_bytes = _build_minimal_pdf("irrelevant")
    outcome = extract_text("blank.pdf", pdf_bytes)
    assert outcome.source_type == "pdf"
    assert any("text layer" in w.lower() or "no extractable" in w.lower() for w in outcome.warnings)


def test_extract_pdf_warns_when_fonts_lack_unicode_mapping():
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(300, 200))
    c.setFont("Helvetica", 12)
    c.drawString(20, 150, "Plain ASCII text, standard simple font.")
    c.save()

    outcome = extract_text("simple_font.pdf", buf.getvalue())
    assert "Plain ASCII text" in outcome.text  # standard text still extracts fine
    assert any("tounicode" in w.lower() or "unicode mapping" in w.lower() for w in outcome.warnings)


def test_extract_pdf_rejects_invalid_file():
    with pytest.raises(ExtractionError):
        extract_text("fake.pdf", b"not a real pdf")


def test_extract_pdf_always_notes_zero_width_limitation():
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(300, 200))
    c.drawString(20, 150, "Ordinary text, nothing unusual.")
    c.save()

    outcome = extract_text("ordinary.pdf", buf.getvalue())
    assert any("zero-width" in w.lower() and "bidi" in w.lower() for w in outcome.warnings)


# ---------------------------------------------------------------------
# .doc (unsupported) and unknown extensions
# ---------------------------------------------------------------------

def test_extract_doc_raises_clear_unsupported_error():
    with pytest.raises(UnsupportedFileTypeError) as exc_info:
        extract_text("legacy.doc", b"anything")
    assert "docx" in exc_info.value.message.lower()


def test_extract_unknown_extension_raises():
    with pytest.raises(UnsupportedFileTypeError):
        extract_text("archive.zip", b"anything")
