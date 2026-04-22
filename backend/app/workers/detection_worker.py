"""Detection worker process entrypoint.

This worker is intentionally lightweight today and is used as a separate
scalable process container. It is ready to be connected to a broker queue
in the next extraction stage.
"""
from __future__ import annotations

import logging
import os
import signal
import time

logger = logging.getLogger("carvision.worker.detection")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

_RUNNING = True


def _handle_signal(signum, _frame):
    global _RUNNING
    logger.info("Received signal %s, shutting down detection worker", signum)
    _RUNNING = False


def main() -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    poll_interval = float(os.getenv("DETECTION_WORKER_POLL_SECONDS", "1.0"))
    logger.info("Detection worker started (poll=%ss)", poll_interval)
    while _RUNNING:
        # Stage-1 isolation: dedicated process boundary for detection workloads.
        # Queue consumption will be attached in the next migration step.
        time.sleep(max(0.1, poll_interval))
    logger.info("Detection worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
