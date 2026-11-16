"""Team accounts for FRC Team 11 (MORT): sign-up with the team join code, sign-in, two roles (admin and base),
sessions, password-reset codes, the activity log and the team's private scouting and live draft
(docs/team_workspaces.md; migrations 0012 and 0015).

There is one workspace, team 11's, created by migration 0015; every account is a membership in it. The package
holds the rules; api/routes/auth.py, api/routes/workspace.py, api/routes/team_scouting.py and
api/routes/live_draft.py are thin HTTP wrappers over it. Every function that touches team-private data takes the
workspace id from a resolved session (workspaces.sessions.SessionContext), never from the request.
"""
