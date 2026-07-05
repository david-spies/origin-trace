"""
Security primitives shared across the API surface.

- SecurityHeadersMiddleware: applies a conservative baseline of HTTP security
  headers to every response (defense-in-depth; this is a text-processing
  tool with a browser-facing dashboard, so clickjacking/MIME-sniffing
  protections are cheap insurance).
- limiter: a per-client-IP rate limiter used to keep the analysis endpoints
  from being used as an unthrottled compute sink.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

limiter = Limiter(key_func=get_remote_address)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Cache-Control"] = "no-store"
        return response
