// Shapes of the Game Manual Manager, season-ruleset, readiness and historical-explorer endpoints
// (api/routes/manual_manager.py, api/routes/explorer.py) and the read-only analysis endpoints the explorer shows.
// The server validates everything; nothing here decides or approves anything.

export type ProcessingStatus = 'not_started' | 'running' | 'succeeded' | 'failed' | 'needs_resolution'

export interface ProcessingAttempt {
  attempt: number
  status: string
  started_at?: string
  finished_at?: string
  requested_by?: string
  error?: { code: string; message: string }
}

export interface ProcessingWarning {
  code: string
  message: string
  page?: number
  topic?: string
}

export interface ManualIdentity {
  seasons_found: number[]
  season: number | null
  revision: string | null
  team_update: number | null
  date: string | null
  title_line: string | null
  declared_season: number
  decision: 'identified' | 'resolved' | 'ambiguous' | 'wrong_season'
  reason: string
}

export interface ProcessingReport {
  status: 'succeeded'
  processor_version: string
  manual_sha256: string
  season: number
  page_count: number
  text_pages: number
  identity: ManualIdentity
  sections: number
  suggestions: number
  extraction_sha256: string
  warnings: ProcessingWarning[]
  authoritative: false
  note: string
}

export interface ProcessingState {
  manual_id: number
  season: number
  content_sha256: string
  processor_version: string
  status: ProcessingStatus
  attempts: ProcessingAttempt[]
  report: ProcessingReport | null
  identity_resolution: { season: number; resolved_by: string; note: string | null; resolved_at: string } | null
  retry_allowed: boolean
  claimed?: boolean
}

export interface Suggestion {
  rule: string
  target: string
  value: unknown
  page: number
  snippet: string
  status: 'machine_extracted_unverified'
}

export interface Extraction {
  processor_version: string
  manual_sha256: string
  season: number
  page_count: number
  identity: ManualIdentity
  pages: { page: number; chars: number; text_sha256: string; error: string | null }[]
  sections: { number: string; title: string; page: number }[]
  topics: Record<string, { pages: number[]; top_pages: number[]; mentions: number }>
  suggestions: Suggestion[]
}

export interface PageText {
  page: number
  chars: number
  text_sha256: string
  error: string | null
  text: string
}

export type RulesetStatus = 'draft' | 'awaiting_review' | 'approved' | 'superseded'

export interface RulesetVersion {
  id: number
  season: number
  version: number
  ruleset_json: Record<string, unknown>
  ruleset_sha256: string
  status: RulesetStatus
  created_by: string
  created_at: string
  submitted_at: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
}

export interface ChecklistInfo {
  items: { id: string; title: string }[]
  guide: string
  control: string
  r15: string
}

export interface Worksheet {
  season: number
  template_from_season: number
  template_ruleset_id: number
  manual: { id: number; sha256: string; processed: boolean } | null
  proposal: Record<string, unknown>
  schema_errors: unknown[]
  verify: { path: string; reason: string; suggestions: Suggestion[]; manual_pages: number[] }[]
  unverified_marker: string
  saved: false
  note: string
}

export interface Coverage {
  events: number
  matches: number
  matches_played: number
  qualification_matches_played: number
  playoff_matches_played: number
  teams: number
  team_event_epa_rows: number
  team_metrics_rows: number
  events_with_metrics: number
  scouting_observations: number
  latest_update: string | null
  latest_match: string | null
  score_breakdown_adapter: boolean
  has_data: boolean
}

export interface Feature {
  key: string
  name: string
  consumes: string[]
  available: boolean
  reasons: string[]
  /** What an available feature still cannot answer this season ("available" means callable, not complete). */
  limitations: string[]
  route: string | null
  requires_human: string | null
}

export type TaskStatus = 'done' | 'failed' | 'ready_for_human' | 'ready_to_run' | 'blocked' | 'waiting_for_2027_data'

export interface Phase6Task {
  id: string
  title: string
  actor: string
  kind: string
  status: TaskStatus
  evidence: string | null
  evidence_exists: boolean
  depends_on: string[]
  waiting_on: string[]
  automatic: boolean
  authorizes: string
  never_by_manual_upload: true
}

export interface Readiness {
  season: number
  coverage: Coverage
  human_inputs: {
    manuals: (import('./types').Manual & { processing: { status: ProcessingStatus; report: ProcessingReport | null } })[]
    game_spec: { id: number; version: number; status: string; complete: boolean; created_by: string;
      reviewed_by: string | null } | null
    ruleset: {
      approved: { id: number; version: number; sha256: string; reviewed_by: string | null } | null
      latest: { id: number; version: number; status: string; created_by: string } | null
    }
  }
  features: Feature[]
  automation_boundary: { automatic: string[]; never_automatic: string[] }
  phase6?: {
    tasks: Phase6Task[]
    done_means: { done_means: string; met: boolean; reasons?: string[] }[]
    status: string
  }
}

export interface SeasonSummary {
  season: number
  coverage: Coverage
}

export interface EventSummary {
  event_key: string
  name: string
  event_code: string
  event_type: number | null
  start_date: string | null
  end_date: string | null
  city: string | null
  state_prov: string | null
  country: string | null
  matches: number
  matches_played: number
  teams: number
}

export interface EventInfo {
  event_key: string
  season: number
  name: string
  start_date: string | null
  end_date: string | null
  city: string | null
  state_prov: string | null
  country: string | null
}

export interface EventTeam {
  team_number: number
  name: string | null
  city: string | null
  state_province: string | null
  country: string | null
  epa_total: string | null
  epa_auto: string | null
  epa_teleop: string | null
  epa_endgame: string | null
  wins: number | null
  losses: number | null
  ties: number | null
  matches_played: number | null
  metrics_computed: boolean
}

export interface EventMatch {
  match_key: string
  competition_level: string
  set_number: number | null
  match_number: number
  scheduled_time: string | null
  score_red: number | null
  score_blue: number | null
  winning_alliance: string | null
  red: number[] | null
  blue: number[] | null
}

export interface TeamSeason {
  team: { team_number: number; name: string | null; city: string | null; state_province: string | null;
    country: string | null; rookie_year: number | null }
  season: number
  events: { event_key: string; name: string; start_date: string | null; epa_total: string | null;
    epa_auto: string | null; epa_teleop: string | null; epa_endgame: string | null; wins: number | null;
    losses: number | null; ties: number | null; matches_played: number | null; metrics_computed: boolean }[]
}

/** The analysis endpoints are shown as returned: their own validation statuses and evidence are the point. */
export type AnalysisBody = Record<string, unknown>
