"""Ingest worker process entrypoint.

Separated runtime process for stream ingest lifecycle work. This gives a
clean path to scale ingest independently from API pods in Kubernetes.
"""
from __future__ import annotations

import logging
import os
import signal
import time

logger = logging.getLogger("carvision.worker.ingest")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

_RUNNING = True


def _handle_signal(signum, _frame):
    global _RUNNING
    logger.info("Received signal %s, shutting down ingest worker", signum)
    _RUNNING = False


def main() -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    poll_interval = float(os.getenv("INGEST_WORKER_POLL_SECONDS", "1.0"))
    logger.info("Ingest worker started (poll=%ss)", poll_interval)
    while _RUNNING:
        time.sleep(max(0.1, poll_interval))
    logger.info("Ingest worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
