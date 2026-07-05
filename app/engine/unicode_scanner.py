"""
Unicode anomaly scanner.

Covers six distinct families of invisible/non-printable Unicode use — four
steganographic/spoofing techniques, plus two "visually blank" families that
a narrower Cc/Cf-only scan would miss entirely:

  1. Zero-width & invisible-format characters (ZWSP, ZWJ, word joiner, ...)
     — the classic "invisible watermark" carrier, one bit per character.
  2. Bidirectional control characters (LRO/RLO/PDF/embeddings/isolates)
     — used for visual text spoofing and can also carry hidden ordering
     information.
  3. Variation selectors (VS1-16, and the VS17-256 supplement block)
     — normally used to select emoji presentation/glyph variants, but a
     documented technique repurposes the 256-codepoint supplement block to
     smuggle arbitrary bytes attached to a visible character.
  4. Unicode Tag characters (U+E0000-U+E007F)
     — originally intended for language tagging, deprecated for that use,
     and now the most common vector for smuggling entire hidden ASCII
     strings behind a single visible character.
  5. Non-standard Unicode space separators (category Zs, e.g. non-breaking
     space, thin space, ideographic space) — these render as blank gaps
     but are neither Cc nor Cf, so a scan scoped only to those two
     categories misses them even though a plain-language "invisible
     character checker" would flag every one of them.
  6. Blank glyphs outside any whitespace/format category (Hangul Filler,
     Braille Pattern Blank) — visually empty characters that Unicode
     classifies as ordinary letters or symbols, used to fake "empty"
     usernames or form fields past naive validation.

Families 1-4 are steganography/spoofing vectors and are reported with a
security framing; families 5-6 are more often accidental (copy-pasted from
a word processor or web page) but are just as invisible to the eye, so
they're detected with equal rigor — a text can carry a hidden payload OR
simply look wrong for reasons a human reader can't see, and this scanner
is meant to catch both.

This module is intentionally deterministic: every finding here is an exact
codepoint match, not a heuristic. That distinction matters downstream — it's
why hidden-character detection is reported with certainty while statistical
generation-likelihood scoring (entropy_analyzer.py) is not.
"""

import unicodedata
from dataclasses import dataclass
from typing import Dict, List

# Characters that are technically in Cc/Cf categories but are legitimate,
# universally-expected formatting whitespace. Never flagged.
_ALLOWED_WHITESPACE = {"\n", "\r", "\t"}

_ZERO_WIDTH = {
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\u2060",  # WORD JOINER
    "\u2061",  # FUNCTION APPLICATION
    "\u2062",  # INVISIBLE TIMES
    "\u2063",  # INVISIBLE SEPARATOR
    "\u2064",  # INVISIBLE PLUS
    "\ufeff",  # ZERO WIDTH NO-BREAK SPACE / BOM
    "\u180e",  # MONGOLIAN VOWEL SEPARATOR
}

_BIDI_CONTROLS = {
    "\u200e", "\u200f",              # LRM, RLM
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # LRE, RLE, PDF, LRO, RLO
    "\u2066", "\u2067", "\u2068", "\u2069",             # LRI, RLI, FSI, PDI
}

# Category Zs ("space separator") characters other than the ordinary
# U+0020 SPACE. These render as blank gaps but are neither Cc nor Cf, so
# they fall outside the format/control scan entirely unless listed here.
# This is the family a generic "invisible character" checker (e.g. NBSP,
# thin space, ideographic space) will flag but a Cc/Cf-only scanner misses.
_UNICODE_SPACES = {
    "\u00a0",  # NO-BREAK SPACE
    "\u1680",  # OGHAM SPACE MARK
    "\u2000", "\u2001", "\u2002", "\u2003", "\u2004",  # EN/EM QUAD, EN/EM/3-PER-EM SPACE
    "\u2005", "\u2006", "\u2007", "\u2008", "\u2009", "\u200a",  # 4/6-PER-EM, FIGURE, PUNCT, THIN, HAIR SPACE
    "\u202f",  # NARROW NO-BREAK SPACE
    "\u205f",  # MEDIUM MATHEMATICAL SPACE
    "\u3000",  # IDEOGRAPHIC SPACE
}

# Characters that are visually blank by design but sit in a Unicode
# category (Lo, So, ...) that has nothing to do with whitespace or
# formatting, so no category-based rule can catch them — they have to be
# listed explicitly. These are documented tricks for producing "empty"
# usernames, filenames, or form fields that pass naive validation.
_BLANK_GLYPHS = {
    "\u3164",  # HANGUL FILLER
    "\uffa0",  # HALFWIDTH HANGUL FILLER
    "\u2800",  # BRAILLE PATTERN BLANK
}


def _is_variation_selector(cp: int) -> bool:
    return (0xFE00 <= cp <= 0xFE0F) or (0xE0100 <= cp <= 0xE01EF)


def _is_tag_character(cp: int) -> bool:
    return 0xE0000 <= cp <= 0xE007F


@dataclass
class Finding:
    position: int
    codepoint: str
    name: str
    category: str
    context_before: str
    context_after: str


class UnicodeScanner:
    """Stateless scanner: every call is independent, nothing is cached or retained."""

    @staticmethod
    def _classify(char: str) -> str | None:
        if char in _ALLOWED_WHITESPACE:
            return None

        cp = ord(char)

        if char in _ZERO_WIDTH:
            return "zero_width"
        if char in _BIDI_CONTROLS:
            return "bidi_control"
        if char in _UNICODE_SPACES:
            return "unicode_space"
        if char in _BLANK_GLYPHS:
            return "blank_glyph"
        if _is_variation_selector(cp):
            return "variation_selector"
        if _is_tag_character(cp):
            return "tag_character"

        category = unicodedata.category(char)
        if category == "Cc":
            return "control"
        if category == "Cf":
            return "other_format"

        return None

    @classmethod
    def scan(cls, text: str) -> List[Finding]:
        findings: List[Finding] = []

        for index, char in enumerate(text):
            category = cls._classify(char)
            if category is None:
                continue

            cp = ord(char)
            name = unicodedata.name(char, f"UNNAMED CONTROL (U+{cp:04X})")

            findings.append(
                Finding(
                    position=index,
                    codepoint=f"U+{cp:04X}",
                    name=name,
                    category=category,
                    context_before=text[max(0, index - 12):index],
                    context_after=text[index + 1:index + 13],
                )
            )

        return findings

    @classmethod
    def category_should_strip(
        cls,
        category: str,
        strip_hidden_unicode: bool,
        strip_bidi_controls: bool,
        strip_unicode_spaces: bool = True,
    ) -> bool:
        if category == "bidi_control":
            return strip_bidi_controls
        if category == "unicode_space":
            return strip_unicode_spaces
        # zero_width, control, variation_selector, tag_character, other_format, blank_glyph
        return strip_hidden_unicode

    @classmethod
    def count_by_category(cls, findings: List[Finding]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for f in findings:
            counts[f.category] = counts.get(f.category, 0) + 1
        return counts
