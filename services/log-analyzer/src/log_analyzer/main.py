from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime

from .analyzer import AnalyzerService
from .config import Settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("log_analyzer")


def _seconds_to_next_hour(now: datetime | None = None) -> int:
    current = now or datetime.utcnow()
    next_hour = current.replace(minute=0, second=0, microsecond=0)
    next_hour = next_hour.timestamp() + 3600
    return max(1, int(next_hour - current.timestamp()))


def run_loop(settings: Settings, once: bool) -> None:
    service = AnalyzerService(settings)

    while True:
        try:
            result = service.run_once()
            logger.info("run completed: %s", result)
        except Exception:
            logger.exception("run failed")

        if once:
            return

        sleep_seconds = min(settings.analyzer_interval_seconds, _seconds_to_next_hour())
        logger.info("sleeping for %s seconds", sleep_seconds)
        time.sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hourly ClickHouse log analyzer")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings.from_env()
    run_loop(settings=settings, once=args.once)


if __name__ == "__main__":
    main()
