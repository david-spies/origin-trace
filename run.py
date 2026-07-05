"""One-command launcher: `python run.py`."""

import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=not settings.is_production,
    )
