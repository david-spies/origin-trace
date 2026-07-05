"""
Statistical structure analyzer.

IMPORTANT FRAMING: nothing in this module can detect a cryptographic
watermark such as Google's SynthID. Those schemes bias a model's token
sampling using a key that is invisible in the surface statistics of the
output text; recovering that signal requires the model provider's detector
and key, not client-side text statistics. Peer-reviewed evaluations of
perplexity/entropy-based "AI text detectors" consistently find they are
unreliable and easy to evade, and this module makes no attempt to pretend
otherwise.

What this module *does* provide is a set of well-established stylometric
signals (lexical diversity, sentence-length variance, character-level
entropy, repetition rate) that measure structural uniformity. Very uniform
text is *somewhat* more common in templated or mechanically produced
content, but plenty of natural writing (legal text, technical docs, form
letters) is also highly uniform, and plenty of generated text is not. The
composite score and confidence band are reported as a weak, exploratory
signal — the API and UI both surface that framing rather than a bare
"AI / not AI" verdict.
"""

import math
import re
from dataclasses import dataclass
from typing import List

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Signal:
    name: str
    value: float
    weight: float
    interpretation: str


@dataclass
class EntropyReport:
    composite_score: float          # 0-10, higher = more natural/varied structure
    signals: List[Signal]
    confidence: str                 # low | moderate | elevated | high
    summary: str


class EntropyAnalyzer:
    MIN_WORDS_FOR_CONFIDENCE = 60

    @classmethod
    def analyze(cls, text: str) -> EntropyReport:
        words = _WORD_RE.findall(text.lower())
        sentences = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]

        signals: List[Signal] = [
            cls._lexical_diversity_signal(words),
            cls._char_bigram_entropy_signal(text),
            cls._sentence_variance_signal(sentences),
            cls._repetition_signal(words),
        ]

        composite = sum(s.value * s.weight for s in signals) / sum(s.weight for s in signals)
        composite = round(max(0.0, min(10.0, composite)), 3)

        confidence = cls._confidence_band(words, sentences)
        summary = cls._summarize(composite, confidence)

        return EntropyReport(composite_score=composite, signals=signals, confidence=confidence, summary=summary)

    # ------------------------------------------------------------------
    # Individual signals — each normalized to a 0-10 "naturalness" scale
    # ------------------------------------------------------------------

    @staticmethod
    def _lexical_diversity_signal(words: List[str]) -> Signal:
        if not words:
            return Signal("lexical_diversity", 0.0, 1.0, "No words to evaluate.")

        counts = {}
        for w in words:
            counts[w] = counts.get(w, 0) + 1
        total = len(words)
        probs = [c / total for c in counts.values()]
        shannon = -sum(p * math.log2(p) for p in probs)
        # Normalize against the entropy of a fully-diverse sample of this
        # length (every word unique), not against this sample's own
        # vocabulary size — the latter masks repetition whenever the
        # repeated words happen to be evenly distributed.
        max_entropy = math.log2(total) if total > 1 else 1.0
        normalized = (shannon / max_entropy) if max_entropy > 0 else 0.0
        scaled = round(min(1.0, normalized) * 10, 3)

        if scaled < 4.0:
            note = "Vocabulary usage is concentrated on a small set of repeated words."
        elif scaled < 7.5:
            note = "Vocabulary usage is moderately varied."
        else:
            note = "Vocabulary usage is highly varied, typical of natural prose."

        return Signal("lexical_diversity", scaled, 1.2, note)

    @staticmethod
    def _char_bigram_entropy_signal(text: str) -> Signal:
        clean = re.sub(r"\s+", " ", text.lower())
        if len(clean) < 2:
            return Signal("character_bigram_entropy", 0.0, 0.8, "Text too short to evaluate.")

        bigrams = [clean[i:i + 2] for i in range(len(clean) - 1)]
        counts = {}
        for bg in bigrams:
            counts[bg] = counts.get(bg, 0) + 1
        total = len(bigrams)
        probs = [c / total for c in counts.values()]
        shannon = -sum(p * math.log2(p) for p in probs)
        # Empirically, natural-language character bigram entropy for
        # alphabetic text typically falls in the ~3.0-4.2 bits/bigram range.
        normalized = min(1.0, shannon / 4.2)
        scaled = round(normalized * 10, 3)

        if scaled < 5.0:
            note = "Character-level patterns are more repetitive than typical prose."
        else:
            note = "Character-level patterns fall within the typical range for prose."

        return Signal("character_bigram_entropy", scaled, 1.0, note)

    @staticmethod
    def _sentence_variance_signal(sentences: List[str]) -> Signal:
        if len(sentences) < 3:
            return Signal("sentence_length_variance", 5.0, 0.6, "Not enough sentences to assess rhythm.")

        lengths = [len(_WORD_RE.findall(s)) for s in sentences]
        mean_len = sum(lengths) / len(lengths)
        if mean_len == 0:
            return Signal("sentence_length_variance", 5.0, 0.6, "Not enough sentences to assess rhythm.")

        variance = sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
        std_dev = math.sqrt(variance)
        coefficient_of_variation = std_dev / mean_len

        # Human writing tends toward CoV roughly in the 0.3-0.7 range.
        # Very low variance (extremely uniform sentence lengths) is the
        # signal of interest here — it is weak on its own.
        scaled = round(min(1.0, coefficient_of_variation / 0.5) * 10, 3)

        if scaled < 4.0:
            note = "Sentence lengths are unusually uniform."
        else:
            note = "Sentence length rhythm shows natural variation."

        return Signal("sentence_length_variance", scaled, 1.0, note)

    @staticmethod
    def _repetition_signal(words: List[str]) -> Signal:
        if len(words) < 10:
            return Signal("phrase_repetition", 5.0, 0.6, "Not enough text to assess repetition.")

        trigrams = [tuple(words[i:i + 3]) for i in range(len(words) - 2)]
        if not trigrams:
            return Signal("phrase_repetition", 5.0, 0.6, "Not enough text to assess repetition.")

        unique_ratio = len(set(trigrams)) / len(trigrams)
        scaled = round(unique_ratio * 10, 3)

        if scaled < 6.0:
            note = "Notable repetition of three-word phrases."
        else:
            note = "Little to no repeated phrasing detected."

        return Signal("phrase_repetition", scaled, 1.0, note)

    # ------------------------------------------------------------------

    @classmethod
    def _confidence_band(cls, words: List[str], sentences: List[str]) -> str:
        if len(words) < cls.MIN_WORDS_FOR_CONFIDENCE or len(sentences) < 3:
            return "low"
        if len(words) < 200:
            return "moderate"
        if len(words) < 600:
            return "elevated"
        return "high"

    @staticmethod
    def _summarize(composite: float, confidence: str) -> str:
        if confidence == "low":
            return "Text sample is too short for a meaningful statistical read; treat this score as indicative only."
        if composite >= 7.0:
            return "Structural signals fall within the typical range for naturally varied writing."
        if composite >= 4.5:
            return "Structural signals show moderate uniformity — not unusual, but worth a second look alongside other evidence."
        return "Structural signals show notable uniformity, a pattern sometimes seen in templated or mechanically produced text."
