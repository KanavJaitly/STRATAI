// The client for team workspaces: sign-in, registration, invitations, passwords, Team Management and team scouting
// (docs/team_workspaces.md). Every route it calls is listed in WORKSPACE_ENDPOINTS, which
// tests/test_frontend_workspace_contract.py checks against the API's live OpenAPI schema in both directions.
//
// The session is an HttpOnly cookie the browser sends on its own (the API is on this origin: the Vite proxy locally,
// the Vercel rewrite when hosted). Nothing here ever reads or stores it. Every write carries X-StratAI-CSRF.

import { API_BASE } from '../api/client'
import { requestJson } from '../api/http'

export const CSRF_HEADER = 'X-StratAI-CSRF'

type Method = 'GET' | 'POST'

export const WORKSPACE_ENDPOINTS = {
  session: ['GET', '/auth/session'],
  registerTeam: ['POST', '/auth/teams/register'],
  initialAdmin: ['POST', '/auth/teams/initial-admin'],
  login: ['POST', '/auth/login'],
  logout: ['POST', '/auth/logout'],
  changePassword: ['POST', '/auth/password/change'],
  forgotPassword: ['POST', '/auth/password/forgot'],
  resetPassword: ['POST', '/auth/password/reset'],
  previewInvitation: ['POST', '/auth/invitations/preview'],
  acceptInvitation: ['POST', '/auth/invitations/accept'],
  workspace: ['GET', '/workspace'],
  members: ['GET', '/workspace/members'],
  invite: ['POST', '/workspace/invitations'],
  resendInvitation: ['POST', '/workspace/invitations/{invitation_id}/resend'],
  revokeInvitation: ['POST', '/workspace/invitations/{invitation_id}/revoke'],
  changeRole: ['POST', '/workspace/members/{membership_id}/role'],
  setStatus: ['POST', '/workspace/members/{membership_id}/status'],
  editMember: ['POST', '/workspace/members/{membership_id}/profile'],
  removeMember: ['POST', '/workspace/members/{membership_id}/remove'],
  memberPasswordReset: ['POST', '/workspace/members/{membership_id}/password-reset'],
  permissions: ['GET', '/workspace/permissions'],
  setPermissions: ['POST', '/workspace/permissions'],
  settings: ['GET', '/workspace/settings'],
  saveSettings: ['POST', '/workspace/settings'],
  activity: ['GET', '/workspace/activity'],
  analytics: ['GET', '/workspace/analytics'],
  scouts: ['GET', '/workspace/scouting/scouts'],
  assignments: ['GET', '/workspace/scouting/assignments'],
  createAssignment: ['POST', '/workspace/scouting/assignments'],
  cancelAssignment: ['POST', '/workspace/scouting/assignments/{assignment_id}/cancel'],
  reports: ['GET', '/workspace/scouting/reports'],
  submitReport: ['POST', '/workspace/scouting/reports'],
  scoutingSummary: ['GET', '/workspace/scouting/summary'],
  drafts: ['GET', '/workspace/alliance-selection/drafts'],
  startDraft: ['POST', '/workspace/alliance-selection/drafts'],
  draft: ['GET', '/workspace/alliance-selection/drafts/{record_id}'],
  recordDraftAction: ['POST', '/workspace/alliance-selection/drafts/{record_id}/actions'],
  undoDraftAction: ['POST', '/workspace/alliance-selection/drafts/{record_id}/undo'],
  correctDraftAction: ['POST', '/workspace/alliance-selection/drafts/{record_id}/corrections'],
  closeDraft: ['POST', '/workspace/alliance-selection/drafts/{record_id}/close'],
  reopenDraft: ['POST', '/workspace/alliance-selection/drafts/{record_id}/reopen'],
  refreshDraftSetup: ['POST', '/workspace/alliance-selection/drafts/{record_id}/setup'],
  draftRecommendations: ['GET', '/workspace/alliance-selection/drafts/{record_id}/recommendations'],
} as const satisfies Record<string, readonly [Method, string]>

type EndpointName = keyof typeof WORKSPACE_ENDPOINTS

export type Role = 'admin' | 'strategy' | 'scouter'
export type VerificationStatus = 'pending_verification' | 'verified' | 'rejected'

export interface SessionInfo {
  authenticated: boolean
  access_policy: 'open' | 'members'
  email_delivery_configured: boolean
  /** False when the server's database lacks the team-account tables (migration 0012). */
  accounts_available?: boolean
  user?: { id: number; name: string; email: string }
  workspace?: { team_number: number; team_name: string; verification_status: VerificationStatus }
  role?: Role
  role_label?: string
  permissions?: string[]
}

export interface RegisteredTeam {
  team_number: number
  team_name: string
  verification_status: VerificationStatus
  known_frc_team: boolean
  frc_team_name: string | null
}

export interface InvitationPreview {
  team_number: number
  team_name: string
  email: string
  full_name: string
  role: Role
  role_label: string
  expires_at: string
  existing_account: boolean
}

export interface WorkspaceOverview {
  team_number: number
  team_name: string
  verification_status: VerificationStatus
  verified_at: string | null
  created_at: string
  settings: { default_event_key: string | null; scouting_instructions: string | null }
  active_members: number
  role: Role
  role_label: string
  permissions: string[]
}

export interface Member {
  membership_id: number
  user_id: number
  name: string
  email: string
  role: Role
  role_label: string
  status: 'active' | 'suspended'
  invitation_status: 'accepted'
  last_login_at: string | null
  joined_at: string
  is_self: boolean
}

export interface PendingInvitation {
  invitation_id: number
  email: string
  name: string
  role: Role
  role_label: string
  expires_at: string
  invited_at: string
  invited_by: string | null
  invitation_status: 'pending' | 'expired'
}

export interface InvitationIssued {
  invitation_id: number
  email: string
  name: string
  role: Role
  expires_at: string
  invitation_link: string
  emailed: boolean
  email_channel: string | null
}

export interface PermissionCell { granted: boolean; editable: boolean; default?: boolean }

export interface PermissionMatrix {
  roles: { role: Role; label: string }[]
  permissions: { permission: string; description: string; admin_only: boolean; roles: Record<Role, PermissionCell> }[]
}

export interface TeamSettings {
  team_number: number
  team_name: string
  default_event_key: string | null
  scouting_instructions: string | null
}

export interface ActivityEntry {
  id: number
  actor: string
  action: string
  action_label: string
  target: string | null
  details: Record<string, unknown>
  at: string
}

export interface ActivityPage {
  entries: ActivityEntry[]
  has_more: boolean
  actions: { action: string; label: string }[]
}

export interface TeamAnalytics {
  members_by_role: Record<Role, { active: number; suspended: number }>
  active_last_7_days: number
  never_signed_in: number
  pending_invitations: number
  expired_invitations: number
  scouting: {
    reports: number
    reports_last_7_days: number
    events: number
    open_assignments: number
    completed_assignments: number
    top_scouts: { name: string; reports: number }[]
  }
}

export interface Assignment {
  assignment_id: number
  event_key: string
  match_key: string
  competition_level: string | null
  set_number: number | null
  match_number: number | null
  scheduled_time: string | null
  team_number: number
  alliance_color: string | null
  assigned_user_id: number
  assigned_to: string
  status: 'assigned' | 'completed' | 'cancelled'
  created_at: string
  report_submitted: boolean
}

export interface ScoutingReport {
  report_id: number
  event_key: string
  match_key: string
  team_number: number
  defense_rating: number | null
  feeding_rating: number | null
  notes: string | null
  assignment_id: number | null
  submitted_at: string
  scout: string
}

export interface ScoutingSummary {
  event_key: string
  source: string
  method: string
  teams: {
    team_number: number
    reports: number
    scouts: number
    profile: {
      defense_score: number | null
      defense_observation_count: number
      defense_agreement: number | null
      defense_insufficient_data: boolean
      feeding_score: number | null
      feeding_observation_count: number
      feeding_agreement: number | null
      feeding_insufficient_data: boolean
    }
  }[]
}

interface CallOptions {
  params?: Record<string, string | number>
  query?: Record<string, string | number | boolean | undefined | null>
  body?: unknown
}

function path(name: EndpointName, params: Record<string, string | number> = {}): string {
  return WORKSPACE_ENDPOINTS[name][1].replace(/\{(\w+)\}/g, (_, key: string) => {
    if (!(key in params)) throw new Error(`missing path parameter ${key}`)
    return encodeURIComponent(String(params[key]))
  })
}

async function call<T>(name: EndpointName, options: CallOptions = {}): Promise<T> {
  const [method] = WORKSPACE_ENDPOINTS[name]
  let url = API_BASE + path(name, options.params)
  const query = Object.entries(options.query ?? {}).filter(([, v]) => v !== undefined && v !== null && v !== '')
  if (query.length) url += '?' + new URLSearchParams(query.map(([k, v]) => [k, String(v)])).toString()
  const headers: Record<string, string> = {}
  let body: string | undefined
  if (method !== 'GET') headers[CSRF_HEADER] = '1'
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  // As in api/client.ts: only reads time out; a write waits for the server's answer so it is never resubmitted blind.
  return requestJson<T>(url, { method, headers, body, timeoutMs: method === 'GET' ? undefined : 0 })
}

export const auth = {
  session: () => call<SessionInfo>('session'),
  registerTeam: (body: { team_number: number; team_name: string; setup_password: string }) =>
    call<RegisteredTeam>('registerTeam', { body }),
  initialAdmin: (body: { team_number: number; setup_password: string; full_name: string; email: string;
    password: string }) => call<SessionInfo>('initialAdmin', { body }),
  login: (body: { team_number: number; email: string; password: string }) => call<SessionInfo>('login', { body }),
  logout: () => call<{ authenticated: false }>('logout'),
  changePassword: (body: { current_password: string; new_password: string }) =>
    call<{ changed: true }>('changePassword', { body }),
  forgotPassword: (body: { team_number: number; email: string }) =>
    call<{ accepted: true; email_delivery_configured: boolean }>('forgotPassword', { body }),
  resetPassword: (body: { token: string; new_password: string }) => call<{ reset: true }>('resetPassword', { body }),
  previewInvitation: (token: string) => call<InvitationPreview>('previewInvitation', { body: { token } }),
  acceptInvitation: (body: { token: string; full_name?: string; password: string }) =>
    call<SessionInfo>('acceptInvitation', { body }),
}

export const workspace = {
  overview: () => call<WorkspaceOverview>('workspace'),
  members: () => call<{ members: Member[]; invitations: PendingInvitation[] }>('members'),
  invite: (body: { email: string; full_name: string; role: Role }) => call<InvitationIssued>('invite', { body }),
  resendInvitation: (id: number) => call<InvitationIssued>('resendInvitation', { params: { invitation_id: id } }),
  revokeInvitation: (id: number) => call<unknown>('revokeInvitation', { params: { invitation_id: id } }),
  changeRole: (id: number, role: Role) => call<unknown>('changeRole', { params: { membership_id: id }, body: { role } }),
  setStatus: (id: number, status: 'active' | 'suspended') =>
    call<unknown>('setStatus', { params: { membership_id: id }, body: { status } }),
  editMember: (id: number, name: string) => call<unknown>('editMember', { params: { membership_id: id }, body: { name } }),
  removeMember: (id: number) => call<unknown>('removeMember', { params: { membership_id: id } }),
  memberPasswordReset: (id: number) =>
    call<{ reset_link: string; emailed: boolean; expires_at: string }>('memberPasswordReset',
      { params: { membership_id: id } }),
  permissions: () => call<PermissionMatrix>('permissions'),
  setPermissions: (role: Role, grants: Record<string, boolean>) =>
    call<{ role: Role; changed: Record<string, unknown> }>('setPermissions', { body: { role, grants } }),
  settings: () => call<TeamSettings>('settings'),
  saveSettings: (body: Partial<Omit<TeamSettings, 'team_number'>>) => call<TeamSettings>('saveSettings', { body }),
  activity: (query: { limit?: number; offset?: number; action?: string } = {}) =>
    call<ActivityPage>('activity', { query }),
  analytics: () => call<TeamAnalytics>('analytics'),
}

export const teamScouting = {
  scouts: () => call<{ membership_id: number; name: string; role: Role }[]>('scouts'),
  assignments: (query: { mine?: boolean; event_key?: string; include_closed?: boolean } = {}) =>
    call<Assignment[]>('assignments', { query }),
  createAssignment: (body: { match_key: string; team_number: number; membership_id: number }) =>
    call<Assignment>('createAssignment', { body }),
  cancelAssignment: (id: number) => call<unknown>('cancelAssignment', { params: { assignment_id: id } }),
  reports: (query: { mine?: boolean; event_key?: string; team_number?: number } = {}) =>
    call<ScoutingReport[]>('reports', { query }),
  submitReport: (body: { match_key: string; team_number: number; defense_rating: number | null;
    feeding_rating: number | null; notes: string | null; assignment_id?: number | null }) =>
    call<ScoutingReport>('submitReport', { body }),
  summary: (eventKey: string) => call<ScoutingSummary>('scoutingSummary', { query: { event_key: eventKey } }),
}

// --- Phase 11: the live alliance-selection draft record (docs/phase11.md) -----------------------------------------

export type DraftActionType = 'captain' | 'pick' | 'decline' | 'backup'

export interface ManualDraftRules {
  n_alliances: number
  picks_per_alliance: number
  declined_team_may_be_picked_later: boolean
  declined_team_may_become_captain: boolean | null
  captain_may_accept_higher_alliance: boolean
  backup_robots: boolean
}

export interface DraftSummary {
  record_id: number; record_uid: string; event_key: string; created_at: string; created_by: string
  record_seq: number; status: 'open' | 'closed'; picks_made: number; complete: boolean
}

export interface DraftEffectiveAction {
  action_id: string; slot_action_id: string; seq: number; type: DraftActionType; seed: number | null
  team_number: number; status: 'accepted' | 'overridden' | 'invalid' | 'not_applied'
  violation: { code: string; message: string } | null; override_reason: string | null; notes: string[]
  summary: string; recorded_by: string; recorded_at: string | null
}

export interface DraftHistoryItem {
  action_id: string; seq: number; type: string; summary: string; override_reason: string | null; in_effect: boolean
  superseded_by: string | null; recorded_by: string; recorded_at: string | null; source: string; mode: string
}

export interface DraftRecord {
  record_id: number; record_uid: string; event_key: string; created_at: string; created_by: string
  can_record: boolean; team_number: number | null; record_seq: number; status: 'open' | 'closed'
  configured: boolean
  setup: { rules: ManualDraftRules & { source: string; ruleset_sha256: string | null; ruleset_variant: string | null;
    captain_rule_established: boolean }; ranks: [number, number][] | null; pool: number[] | null; missing: string[];
    provenance: Record<string, unknown> } | null
  value_kind: 'observed'
  alliances: { seed: number; captain: number | null; picks: number[]; projected_captain: number | null }[]
  turn: { index: number; round: number | null; seed: number; captain_named: boolean; expected_captain: number | null;
    expected_captain_reason: string | null } | null
  complete: boolean
  available: { team_number: number; rank: number | null; projected_captain_of: number | null; declined_earlier: boolean }[]
  unavailable: { team_number: number; reason: 'captain' | 'picked' | 'declined' | 'backup' | 'projected_captain';
    rank: number | null;
    seed: number | null }[]
  declined: { team_number: number; seed: number | null }[]
  backups: { team_number: number; seed: number | null }[]
  flags: { action_id: string; status: string; code: string | null; message: string | null }[]
  effective: DraftEffectiveAction[]
  history: DraftHistoryItem[]
}

export interface RecommendedTeam {
  team_number: number
  ordering_position: number | null
  win_event: { display: string | null; validation: { status: string; reasons: string[] } } | null
  reach_finals: { display: string | null; validation: { status: string; reasons: string[] } } | null
  configuration: number[] | null
  profile: Record<string, unknown> | null
}

export interface DraftRecommendations {
  record_id: number; record_seq: number; computed_at: string; status: 'current' | 'withheld'
  withheld: { code: string; message: string } | null
  value_kind: 'model_prediction'
  source: 'engine_p6_m7' | 'fallback_p11_fb1' | null
  validation: { status: string; reasons: string[] } | null
  engine_refusal: { code: string; message: string } | null
  seed: number | null; selecting_as: 'on_alliance' | 'projected_captain' | null; turns_before: number | null
  primary: RecommendedTeam | null; backups: RecommendedTeam[]; unranked_available: number[]
  excluded: { team_number: number; reason: string }[]; movement: string[]
  provenance: Record<string, unknown>; timing_ms: Record<string, number>
}

/** A stable id for an entry, created here so that a retried write is idempotent (and, in Phase 12, local-first). */
export function newActionId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx'.replace(/x/g, () => Math.floor(Math.random() * 16).toString(16))
}

export const liveDraft = {
  list: (eventKey?: string) => call<DraftSummary[]>('drafts', { query: { event_key: eventKey } }),
  start: (body: { event_key: string; manual_rules?: ManualDraftRules | null; record_uid?: string; action_id?: string }) =>
    call<DraftRecord>('startDraft', { body: { record_uid: newActionId(), action_id: newActionId(), ...body } }),
  get: (id: number) => call<DraftRecord>('draft', { params: { record_id: id } }),
  record: (id: number, body: { type: DraftActionType; seed: number | null; team_number: number;
    override_reason?: string | null; action_id?: string }) =>
    call<DraftRecord>('recordDraftAction', { params: { record_id: id },
      body: { action_id: newActionId(), client_recorded_at: new Date().toISOString(), ...body } }),
  undo: (id: number, targetActionId: string) =>
    call<DraftRecord>('undoDraftAction', { params: { record_id: id },
      body: { target_action_id: targetActionId, action_id: newActionId() } }),
  correct: (id: number, body: { target_action_id: string; replacement: { type: DraftActionType; seed: number | null;
    team_number: number } | null; override_reason?: string | null }) =>
    call<DraftRecord>('correctDraftAction', { params: { record_id: id }, body: { action_id: newActionId(), ...body } }),
  close: (id: number) => call<DraftRecord>('closeDraft', { params: { record_id: id }, body: { action_id: newActionId() } }),
  reopen: (id: number) => call<DraftRecord>('reopenDraft', { params: { record_id: id }, body: { action_id: newActionId() } }),
  refreshSetup: (id: number, manualRules?: ManualDraftRules | null) =>
    call<DraftRecord>('refreshDraftSetup', { params: { record_id: id },
      body: { action_id: newActionId(), manual_rules: manualRules ?? null } }),
  recommendations: (id: number) => call<DraftRecommendations>('draftRecommendations', { params: { record_id: id } }),
}

/** A link the API returned as a path ("/auth/invite#token=...") made absolute for copying. */
export function absoluteLink(link: string): string {
  return /^https?:\/\//.test(link) ? link : window.location.origin + link
}

/** The token in the page's URL fragment (#token=...), which browsers never send to any server. */
export function tokenFromHash(hash: string): string {
  return new URLSearchParams(hash.replace(/^#/, '')).get('token') ?? ''
}
