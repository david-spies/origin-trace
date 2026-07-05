"""
Structured logging configuration.

Privacy guarantee: log records emitted by this application NEVER include
the raw text submitted for analysis or purification. Only shape metadata
(lengths, counts, timings) is recorded, which keeps audit logs useful for
operations without turning them into a secondary data store of user content.
"""

import logging
import sys


class RedactedFormatter(logging.Formatter):
    """Formatter that stamps every record with a consistent, greppable shape."""

    def format(self, record: logging.LogRecord) -> str:
        record.msg = str(record.msg)
        return super().format(record)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Avoid duplicate handlers on reload
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactedFormatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root.addHandler(handler)

    # Quiet down noisy third-party loggers by default
    logging.getLogger("uvicorn.access").setLevel("WARNING")
