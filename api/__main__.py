"""Run the API under uvicorn: `python -m api`.

This is the only module in the api package that configures logging handlers,
matching the convention data/orchestrator.py already follows -- library modules
call logging.getLogger(__name__) and nothing else; the process entry point calls
logging.basicConfig. The format string is the orchestrator's, so pipeline logs
and API logs are the same shape.
"""

from __future__ import annotations

import logging

import uvicorn

from api.app import create_app
from data.config import Settings


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def main() -> None:
    """Configure logging, build the application, and serve it."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.api_host,
        port=settings.api_port,
        # uvicorn's own access log would duplicate RequestLoggingMiddleware's
        # line, in a different format and without the request id.
        access_log=False,
    )


if __name__ == "__main__":
    main()
