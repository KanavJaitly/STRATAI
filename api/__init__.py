"""StratAI HTTP API.

Phase 3 Milestone 12 built the foundation -- app factory, health and readiness
endpoints, one structured error shape, request logging, and CORS. Milestone 13
added the first data endpoint on top of it, api.routes.metrics: a read-only
GET /teams/{team_number}/events/{event_key}/metrics.

Every route here is a read. Nothing in this package writes, and there is no
authentication yet -- Milestone 7's scouting submission path is still called as
a service function with no HTTP route in front of it. Auth and rate limiting
are a real prerequisite for exposing that over HTTP, and a separate, later
piece of work; they are not what a public read endpoint is waiting on.

Dependency direction, following docs/data_pipeline.md section 2.3: api imports
data and database, never the reverse. The API is the outermost layer.

    from api import create_app
    app = create_app()

Or run it directly: python -m api
"""

from api.app import create_app


__all__ = ["create_app"]
