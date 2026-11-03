"""Team workspaces: individual accounts, team registration, roles and permissions, invitations, sessions, the
activity log and each team's private scouting (docs/team_workspaces.md, migration 0012).

The package holds the rules; api/routes/auth.py, api/routes/workspace.py and api/routes/team_scouting.py are thin
HTTP wrappers over it. Every function that touches team-private data takes the caller's workspace id from a
resolved session (workspaces.sessions.SessionContext), never from the request, which is what keeps one team's data
out of another team's reach.
"""
