"""HTTP routers.

  * health  -- liveness and readiness (Phase 3 Milestone 12), mounted at the
    application root, outside Settings.api_prefix, so probes never move.
  * metrics -- the team metrics endpoint (Phase 3 Milestone 13), mounted under
    Settings.api_prefix like every data route after it.
"""
