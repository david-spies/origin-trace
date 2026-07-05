"""
Purification pipeline.

Takes the deterministic findings from UnicodeScanner and produces a cleaned
string, honoring the caller's options for which anomaly families to strip
and whether to apply Unicode normalization afterward. Never touches disk;
operates entirely on in-memory strings so the original payload has no
footprint beyond the lifetime of the request.
"""

import unicodedata
from dataclasses import dataclass
from typing import Dict

from app.engine.unicode_scanner import UnicodeScanner


@dataclass
class PurificationOutcome:
    original_length: int
    purified_length: int
    removed_count: int
    removed_by_category: Dict[str, int]
    purified_text: str
    normalization_applied: str


class Purifier:
    @staticmethod
    def purify(
        text: str,
        strip_hidden_unicode: bool = True,
        strip_bidi_controls: bool = True,
        strip_unicode_spaces: bool = True,
        normalize_form: str = "NFC",
    ) -> PurificationOutcome:
        findings = UnicodeScanner.scan(text)
        original_length = len(text)

        removed_by_category: Dict[str, int] = {}
        kept_chars = []

        flagged_positions = {}
        for f in findings:
            if UnicodeScanner.category_should_strip(
                f.category, strip_hidden_unicode, strip_bidi_controls, strip_unicode_spaces
            ):
                flagged_positions[f.position] = f.category

        for index, char in enumerate(text):
            if index in flagged_positions:
                category = flagged_positions[index]
                removed_by_category[category] = removed_by_category.get(category, 0) + 1
                continue
            kept_chars.append(char)

        purified_text = "".join(kept_chars)

        if normalize_form in ("NFC", "NFKC"):
            purified_text = unicodedata.normalize(normalize_form, purified_text)

        return PurificationOutcome(
            original_length=original_length,
            purified_length=len(purified_text),
            removed_count=sum(removed_by_category.values()),
            removed_by_category=removed_by_category,
            purified_text=purified_text,
            normalization_applied=normalize_form,
        )
