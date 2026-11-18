-- 0016: three more team roles: strategy (Strategy team), drive (Drive team) and scout (Scout).
-- Widens the role CHECK on team_memberships; changes no row. What each role may do is fixed in code
-- (workspaces/permissions.py ROLE_GRANTS), as since 0015.

ALTER TABLE team_memberships DROP CONSTRAINT team_memberships_role_check;
ALTER TABLE team_memberships ADD CONSTRAINT team_memberships_role_check CHECK (role IN ('admin', 'base', 'strategy', 'drive', 'scout'));
