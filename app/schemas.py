"""
Request/response contracts.

These models are the API's public interface — every field here shows up in
the auto-generated OpenAPI docs, so descriptions are written for a consumer
who has never seen the source.
"""

from enum import Enum
from typing import List, Literal

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------

class TextPayload(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        description="Raw text to inspect. Sent once, processed in memory, and never persisted.",
    )

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must contain non-whitespace content")
        return value


class PurifyOptions(BaseModel):
    strip_hidden_unicode: bool = Field(True, description="Remove zero-width, control, tag, variation-selector, and blank-glyph characters.")
    strip_bidi_controls: bool = Field(True, description="Remove bidirectional override/embedding characters used for visual spoofing.")
    strip_unicode_spaces: bool = Field(
        True,
        description="Remove non-standard Unicode space separators (NBSP, thin space, ideographic space, ...). "
        "Off by user choice preserves cases where such spacing is intentional typography.",
    )
    normalize_form: Literal["none", "NFC", "NFKC"] = Field(
        "NFC",
        description="Optional Unicode normalization applied after stripping. NFKC also folds many homoglyph/compatibility variants.",
    )


class PurifyRequest(TextPayload):
    options: PurifyOptions = Field(default_factory=PurifyOptions)


# --------------------------------------------------------------------------
# Shared finding types
# --------------------------------------------------------------------------

class AnomalyCategory(str, Enum):
    zero_width = "zero_width"
    control = "control"
    bidi_control = "bidi_control"
    variation_selector = "variation_selector"
    tag_character = "tag_character"
    other_format = "other_format"
    unicode_space = "unicode_space"
    blank_glyph = "blank_glyph"


class UnicodeAnomaly(BaseModel):
    position: int = Field(..., description="Zero-indexed character offset within the submitted text.")
    codepoint: str = Field(..., description="Formal Unicode codepoint, e.g. U+200B.")
    name: str = Field(..., description="Formal Unicode character name.")
    category: AnomalyCategory = Field(..., description="Functional grouping used to explain risk and origin.")
    context_before: str = Field("", description="Up to 12 visible characters preceding the anomaly, for locating it.")
    context_after: str = Field("", description="Up to 12 visible characters following the anomaly.")


class EntropySignal(BaseModel):
    name: str = Field(..., description="Name of the individual statistical signal.")
    value: float = Field(..., description="Computed value of the signal.")
    weight: float = Field(..., description="Relative weight this signal carries in the composite score.")
    interpretation: str = Field(..., description="Plain-language read of this specific signal.")


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------

class AnalysisResult(BaseModel):
    has_hidden_unicode: bool
    hidden_character_count: int
    anomalies: List[UnicodeAnomaly]

    composite_entropy_score: float = Field(
        ..., description="Blended 0-10 statistical uniformity score. Lower values indicate more machine-like structural regularity."
    )
    signals: List[EntropySignal] = Field(..., description="Individual statistical measurements contributing to the composite score.")
    statistical_confidence: Literal["low", "moderate", "elevated", "high"] = Field(
        ..., description="Qualitative confidence band for the statistical assessment — never a binary verdict."
    )
    statistical_summary: str = Field(..., description="One-sentence, plain-language summary of the statistical finding.")

    character_count: int
    word_count: int

    disclaimer: str = Field(
        default=(
            "Hidden-character detection is deterministic and exact. Statistical generation-likelihood scoring is a "
            "heuristic signal, not a cryptographic watermark decoder — it cannot confirm or rule out use of a specific "
            "model's watermarking scheme (e.g. SynthID) and should be used as one input among several, not as sole evidence."
        )
    )


class PurificationResult(BaseModel):
    original_length: int
    purified_length: int
    removed_count: int
    removed_by_category: dict[AnomalyCategory, int]
    purified_text: str
    normalization_applied: str


class ExtractionResult(BaseModel):
    text: str = Field(..., description="Extracted text content, exactly as found in the source file.")
    source_filename: str
    source_type: Literal["txt", "html", "docx", "pdf"]
    character_count: int
    warnings: List[str] = Field(default_factory=list, description="Non-fatal issues encountered during extraction, e.g. pages with no text layer.")


class HealthStatus(BaseModel):
    status: Literal["ok"]
    version: str
    engine_ready: bool
