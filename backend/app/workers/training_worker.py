"""Training worker process entrypoint.

Dedicated worker boundary for model-training jobs. This process can be
scheduled on compute/GPU nodes independently from API pods.
"""
from __future__ import annotations

import logging
import os
import signal
import time

logger = logging.getLogger("carvision.worker.training")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

_RUNNING = True


def _handle_signal(signum, _frame):
    global _RUNNING
    logger.info("Received signal %s, shutting down training worker", signum)
    _RUNNING = False


def main() -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    poll_interval = float(os.getenv("TRAINING_WORKER_POLL_SECONDS", "2.0"))
    logger.info("Training worker started (poll=%ss)", poll_interval)
    while _RUNNING:
        time.sleep(max(0.2, poll_interval))
    logger.info("Training worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
