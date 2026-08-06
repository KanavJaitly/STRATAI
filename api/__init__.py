"""StratAI HTTP API.

Phase 3 Milestone 12: the application foundation only -- app factory, health and
readiness endpoints, one structured error shape, request logging, and CORS.
There are deliberately no metrics or data endpoints here; the team metrics
endpoint is Milestone 13, and this package exists to give it somewhere to land.

Dependency direction, following docs/data_pipeline.md section 2.3: api imports
data and database, never the reverse. The API is the outermost layer.

    from api import create_app
    app = create_app()

Or run it directly: python -m api
"""

from api.app import create_app


__all__ = ["create_app"]
