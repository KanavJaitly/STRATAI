// Signed-in sessions for component tests. The whole app is behind sign-in, so a test that renders the shell without
// an AuthProvider wraps it in SignedInAs to stand for a member. All data here is synthetic.

import type { ReactNode } from 'react'

import type { SessionInfo } from '../auth/api'
import { AuthContext, makeAuth } from '../auth/authState'

// Every permission an administrator holds (workspaces/permissions.py ALL_PERMISSIONS).
export const ADMIN_PERMISSIONS = ['team_info', 'event_analysis', 'qualification_forecast', 'season_explorer',
  'match_predictions', 'team_analytics', 'alliance_selection', 'alliance_selection_record', 'strategy_tools',
  'platform_inputs', 'scouting_forms', 'scouting_submit', 'scouting_view', 'scouting_assign', 'team_overview',
  'team_management',
  'team_settings', 'activity_log']
// What a base member holds (workspaces/permissions.py ROLE_GRANTS["base"]).
export const BASE_PERMISSIONS = ['event_analysis', 'qualification_forecast', 'team_info']

function signedIn(role: 'admin' | 'base', permissions: string[]): SessionInfo {
  return { authenticated: true, access_policy: 'members', email_delivery_configured: false, signup_open: true,
    user: { id: role === 'admin' ? 1 : 2, name: role === 'admin' ? 'Ada Admin' : 'Bo Base',
      email: `${role}@example.test` },
    workspace: { team_number: 11, team_name: 'MORT', verification_status: 'verified' }, role,
    role_label: role === 'admin' ? 'Administrator' : 'Member', permissions }
}

export const ADMIN_SESSION = signedIn('admin', ADMIN_PERMISSIONS)
export const BASE_SESSION = signedIn('base', BASE_PERMISSIONS)

/** Provides session as the signed-in member, without calling GET /auth/session. */
export function SignedInAs({ session = ADMIN_SESSION, children }: { session?: SessionInfo; children: ReactNode }) {
  const value = makeAuth(true, session, () => {}, async () => {}, async () => {})
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
