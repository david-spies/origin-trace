"""Unit tests for the Origin Trace detection/purification engine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.entropy_analyzer import EntropyAnalyzer
from app.engine.purifier import Purifier
from app.engine.unicode_scanner import UnicodeScanner


def test_scanner_detects_zero_width_space():
    text = "Hello\u200bWorld"
    findings = UnicodeScanner.scan(text)
    assert len(findings) == 1
    assert findings[0].category == "zero_width"
    assert findings[0].codepoint == "U+200B"


def test_scanner_detects_tag_characters():
    # U+E0041 = TAG LATIN CAPITAL LETTER A
    text = "Visible\U000E0041\U000E0042Text"
    findings = UnicodeScanner.scan(text)
    assert len(findings) == 2
    assert all(f.category == "tag_character" for f in findings)


def test_scanner_detects_bidi_overrides():
    text = "abc\u202edef"
    findings = UnicodeScanner.scan(text)
    assert len(findings) == 1
    assert findings[0].category == "bidi_control"


def test_scanner_ignores_normal_whitespace():
    text = "Line one\nLine two\tTabbed"
    findings = UnicodeScanner.scan(text)
    assert findings == []


def test_scanner_clean_text_has_no_findings():
    text = "This is a perfectly normal sentence with no hidden characters."
    assert UnicodeScanner.scan(text) == []


def test_scanner_detects_nonbreaking_and_exotic_spaces():
    text = "Hello\u00a0World\u2009Test\u3000End"
    findings = UnicodeScanner.scan(text)
    assert len(findings) == 3
    assert all(f.category == "unicode_space" for f in findings)
    assert findings[0].codepoint == "U+00A0"


def test_scanner_detects_blank_glyphs():
    text = "Name\u3164Field\u2800End"
    findings = UnicodeScanner.scan(text)
    assert len(findings) == 2
    assert all(f.category == "blank_glyph" for f in findings)


def test_scanner_ignores_ordinary_ascii_space():
    text = "This has ordinary spaces only."
    assert UnicodeScanner.scan(text) == []


def test_purifier_strip_unicode_spaces_toggle():
    text = "A\u00a0B"
    kept = Purifier.purify(text, strip_unicode_spaces=False)
    assert kept.removed_count == 0
    assert "\u00a0" in kept.purified_text

    stripped = Purifier.purify(text, strip_unicode_spaces=True)
    assert stripped.removed_count == 1
    assert stripped.purified_text == "AB"


def test_purifier_removes_flagged_categories():
    text = "Secret\u200b\u200bMessage\u202e"
    outcome = Purifier.purify(text, strip_hidden_unicode=True, strip_bidi_controls=True)
    assert outcome.removed_count == 3
    assert outcome.purified_text == "SecretMessage"
    assert "zero_width" in outcome.removed_by_category
    assert "bidi_control" in outcome.removed_by_category


def test_purifier_respects_options_to_keep_bidi():
    text = "abc\u202edef"
    outcome = Purifier.purify(text, strip_hidden_unicode=True, strip_bidi_controls=False)
    assert outcome.removed_count == 0
    assert "\u202e" in outcome.purified_text


def test_purifier_normalizes_form():
    # 'é' as e + combining acute accent, should compose under NFC
    text = "cafe\u0301"
    outcome = Purifier.purify(text, normalize_form="NFC")
    assert outcome.purified_text == "café"


def test_entropy_analyzer_handles_empty_and_short_text():
    report = EntropyAnalyzer.analyze("Hi.")
    assert report.confidence == "low"
    assert 0.0 <= report.composite_score <= 10.0


def test_entropy_analyzer_flags_high_repetition():
    repetitive = "buy now buy now buy now buy now buy now buy now buy now buy now buy now buy now " * 5
    report = EntropyAnalyzer.analyze(repetitive)
    diversity_signal = next(s for s in report.signals if s.name == "lexical_diversity")
    assert diversity_signal.value < 5.0


def test_entropy_analyzer_natural_text_scores_reasonably():
    natural = (
        "The old lighthouse keeper had seen a thousand storms roll in from the north, "
        "yet each one still made him pause at the window, coffee cooling in his hand, "
        "wondering whether tonight would be the night the light finally failed him. "
        "He had patched the mechanism twice this winter alone, cursing the rust and the "
        "salt air in equal measure, but some part of him suspected the real problem was "
        "simply age — his own, as much as the tower's."
    )
    report = EntropyAnalyzer.analyze(natural)
    assert report.composite_score > 3.0
