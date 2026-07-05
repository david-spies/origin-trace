"""
Application entrypoint.

Wires together configuration, logging, security middleware, rate limiting,
the versioned API router, and — for the all-in-one local deployment —
serves the static dashboard directly so the whole tool runs as a single
process on a single port.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import __version__
from app.api.routes import router as api_router
from app.config import get_settings
from app.core.logging_config import configure_logging
from app.core.security import SecurityHeadersMiddleware, limiter

settings = get_settings()
configure_logging(settings.log_level)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="Origin Trace",
    version=__version__,
    description=(
        "Enterprise-grade detection, structural analysis, and purification of hidden "
        "Unicode signatures in text, paired with heuristic statistical structure scoring."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(api_router)

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=not settings.is_production)
