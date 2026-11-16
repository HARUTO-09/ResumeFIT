"""Structured JSON logs: one line per request, with a request id and no personal data.

Only metadata is logged (path, status, latency, score, band, model version,
error code). Resume and JD text never go to the log.
"""

import json
import logging
import sys

logger = logging.getLogger("resumefit")


def setup_logging(level: str = "INFO") -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False


def log_event(event: str, **fields) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str))
