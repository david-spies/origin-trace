"""
Route layer.

Thin by design: every handler validates size limits, delegates to the
engine, and maps engine output onto the response schema. No business logic
lives here.
"""

import logging

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.config import get_settings
from app.core.security import limiter
from app.engine.entropy_analyzer import EntropyAnalyzer
from app.engine.extractors import ExtractionError, UnsupportedFileTypeError, extract_text
from app.engine.purifier import Purifier
from app.engine.unicode_scanner import UnicodeScanner
from app.schemas import (
    AnalysisResult,
    EntropySignal,
    ExtractionResult,
    HealthStatus,
    PurificationResult,
    PurifyRequest,
    TextPayload,
    UnicodeAnomaly,
)

logger = logging.getLogger("origin_trace.api")
router = APIRouter(prefix="/api/v1", tags=["origin-trace"])

_WORD_RE = __import__("re").compile(r"[A-Za-z0-9']+")


def _enforce_length(text: str) -> None:
    settings = get_settings()
    if len(text) > settings.max_text_length:
        raise HTTPException(
            status_code=413,
            detail=f"Payload exceeds the configured limit of {settings.max_text_length} characters.",
        )


@router.post("/analyze", response_model=AnalysisResult)
@limiter.limit(f"{get_settings().rate_limit_per_minute}/minute")
async def analyze_payload(request: Request, payload: TextPayload) -> AnalysisResult:
    _enforce_length(payload.text)

    try:
        findings = UnicodeScanner.scan(payload.text)
        report = EntropyAnalyzer.analyze(payload.text)

        anomalies = [
            UnicodeAnomaly(
                position=f.position,
                codepoint=f.codepoint,
                name=f.name,
                category=f.category,
                context_before=f.context_before,
                context_after=f.context_after,
            )
            for f in findings
        ]

        signals = [
            EntropySignal(name=s.name, value=s.value, weight=s.weight, interpretation=s.interpretation)
            for s in report.signals
        ]

        logger.info(
            "analyze completed | chars=%d hidden=%d confidence=%s",
            len(payload.text), len(findings), report.confidence,
        )

        return AnalysisResult(
            has_hidden_unicode=len(findings) > 0,
            hidden_character_count=len(findings),
            anomalies=anomalies,
            composite_entropy_score=report.composite_score,
            signals=signals,
            statistical_confidence=report.confidence,
            statistical_summary=report.summary,
            character_count=len(payload.text),
            word_count=len(_WORD_RE.findall(payload.text)),
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("analyze pipeline failure")
        raise HTTPException(status_code=500, detail="Internal analysis pipeline failure.") from exc


@router.post("/purify", response_model=PurificationResult)
@limiter.limit(f"{get_settings().rate_limit_per_minute}/minute")
async def purify_payload(request: Request, payload: PurifyRequest) -> PurificationResult:
    _enforce_length(payload.text)

    try:
        outcome = Purifier.purify(
            text=payload.text,
            strip_hidden_unicode=payload.options.strip_hidden_unicode,
            strip_bidi_controls=payload.options.strip_bidi_controls,
            strip_unicode_spaces=payload.options.strip_unicode_spaces,
            normalize_form=payload.options.normalize_form,
        )

        logger.info("purify completed | chars=%d removed=%d", outcome.original_length, outcome.removed_count)

        return PurificationResult(
            original_length=outcome.original_length,
            purified_length=outcome.purified_length,
            removed_count=outcome.removed_count,
            removed_by_category=outcome.removed_by_category,
            purified_text=outcome.purified_text,
            normalization_applied=outcome.normalization_applied,
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("purify pipeline failure")
        raise HTTPException(status_code=500, detail="Internal purification pipeline failure.") from exc


@router.post("/extract", response_model=ExtractionResult)
@limiter.limit(f"{get_settings().rate_limit_per_minute}/minute")
async def extract_payload(request: Request, file: UploadFile = File(...)) -> ExtractionResult:
    settings = get_settings()

    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file has no filename to determine its type.")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.max_upload_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the configured limit of {settings.max_upload_size_mb} MB.",
        )

    try:
        outcome = extract_text(file.filename, content)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=415, detail=exc.message) from exc
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("extraction pipeline failure")
        raise HTTPException(status_code=500, detail="Internal extraction pipeline failure.") from exc

    _enforce_length(outcome.text)

    logger.info(
        "extract completed | filename=%s type=%s chars=%d warnings=%d",
        file.filename, outcome.source_type, len(outcome.text), len(outcome.warnings),
    )

    return ExtractionResult(
        text=outcome.text,
        source_filename=file.filename,
        source_type=outcome.source_type,
        character_count=len(outcome.text),
        warnings=outcome.warnings,
    )


@router.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    from app import __version__
    return HealthStatus(status="ok", version=__version__, engine_ready=True)
