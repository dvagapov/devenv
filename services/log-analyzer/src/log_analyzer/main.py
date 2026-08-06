from __future__ import annotations

import uvicorn

from .config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "log_analyzer.api:app",
        host=settings.http_host,
        port=settings.http_port,
    )


if __name__ == "__main__":
    main()
