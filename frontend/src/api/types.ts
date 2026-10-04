// Shapes returned by the STRATAI human-input API (api/routes/human_inputs.py, data/human_inputs.py).
// The structured payloads mirror the frozen backend models: GameSpec (data/game_spec.py), CapabilityIntake and
// Rubric (ml/gameanalysis/capability.py), Codebook and Coding (data/design_reference.py), ActionFunctionMap
// (ml/gameanalysis/rules_p5d13.py). The server validates every write against those models; nothing here does.

export type Period = 'auto' | 'teleop' | 'endgame'

export interface ScoringAction {
  action_id: string
  name: string
  period: Period
  points: number
  unit: string
  field_element_id: string | null
  action_type: string
  manual_section: string
}

export interface RankingPointRule {
  rule_id: string
  description: string
  ranking_points: number
  manual_section: string
}

export interface FieldElement {
  element_id: string
  name: string
  count: number
  element_type: string
  manual_section: string
}

/** What a person enters. The server owns season, source.entered_by, the entry times and llm_used (always false). */
export interface GameSpecDraft {
  game_name: string
  match_length: { auto_seconds: number; teleop_seconds: number; endgame_seconds: number }
  scoring_actions: ScoringAction[]
  ranking_point_rules: RankingPointRule[]
  field_elements: FieldElement[]
  source: { manual_title: string; manual_version: string }
}

export interface Manual {
  id: number
  season: number
  game_name: string
  filename: string
  media_type: string
  byte_size: number
  content_sha256: string
  uploaded_by: string
  uploaded_at: string
}

export type SpecStatus = 'draft' | 'awaiting_review' | 'approved' | 'superseded'

export interface ValidationProblem {
  field: string
  message: string
}

export interface SpecVersion {
  id: number
  season: number
  version: number
  spec_json: Partial<GameSpecDraft> & Record<string, unknown>
  complete: boolean
  validation_errors: ValidationProblem[]
  spec_sha256: string | null
  manual_id: number | null
  based_on_id: number | null
  status: SpecStatus
  created_by: string
  created_at: string
  entry_started_at: string
  submitted_at: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
}

export type SpecState =
  | 'no_structured_spec'
  | 'structured_spec_incomplete'
  | 'draft_complete_not_submitted'
  | 'awaiting_human_review'
  | 'reviewed_approved'
  | 'superseded'

export interface SeasonWorkflow {
  season: number
  source_uploaded: boolean
  manuals: number
  spec_versions: number
  spec_state: SpecState
  approved_version: number | null
  entry_started_at: string | null
  note: string
}

export type Level = 0 | 1 | 2 | 3

export interface CapabilityPayload {
  team_number: number | null
  budget_usd: number
  manufacturing: Level
  programming: Level
  mentoring: Level
  notes: string
}

export type ProfileStatus = 'active' | 'archived' | 'superseded'

export interface Profile {
  id: number
  profile_key: string
  version: number
  payload: CapabilityPayload & { profile_id: string; submitted_at: string }
  raw_payload_id: number | null
  based_on_id: number | null
  status: ProfileStatus
  created_by: string
  created_at: string
}

export interface RequirementEvaluation {
  archetype: string
  tier: number
  priority: number
  feasible: boolean
  candidate: boolean
  requirements_met: string[]
  requirements_unmet: string[]
  achievable_features: string[]
}

export interface Recommendation {
  label: string
  profile_id: string
  profile_version: number
  season: number
  rubric_version: string
  rubric_sha256: string
  realistic_ceiling_tier: number | null
  recommended_archetype: string | null
  achievable_features: string[]
  candidate_archetypes: string[]
  candidates_note: string
  limitations: string[]
  explanation: RequirementEvaluation[]
}

export type ArtifactKind =
  | 'codebook'
  | 'coding'
  | 'consensus_coding'
  | 'action_function_map'
  | 'rubric'
  | 'mentor_review'

export type ArtifactStatus = 'submitted' | 'established' | 'superseded'

export interface Artifact<P = Record<string, unknown>> {
  id: number
  kind: ArtifactKind
  season: number
  author: string
  version: number
  payload: P
  payload_sha256: string
  status: ArtifactStatus
  created_at: string
  established_by: string | null
  established_at: string | null
  note: string | null
}

export interface CodebookPayload {
  version: string
  authored_by?: string
  functions: Record<string, string>
}

export interface CodingPayload {
  coder?: string
  codebook_sha256?: string
  labels: Record<string, string[]>
}

export interface ActionMapPayload {
  version: string
  authored_by?: string
  codebook_sha256?: string
  mapping: Record<string, string[]>
}

export interface ArchetypeRule {
  archetype: string
  tier: number
  priority: number
  min_budget_usd: number
  min_levels: Partial<Record<'manufacturing' | 'programming' | 'mentoring', number>>
  achievable_features: string[]
}

export interface RubricPayload {
  version: string
  authored_by?: string
  season?: number
  archetypes: ArchetypeRule[]
}

export interface MentorReviewPayload {
  reviewer?: string
  reviewed_at: string
  profiles_reviewed: string[]
  notes: string
}

export interface DesignExample {
  row_id: number
  year: number
  team: number
  game_name: string
  micro_archetype: string
  technical_specifications: string
  key_characteristic: string
  label: string
}

export type KappaStatus =
  | { state: 'awaiting_codings'; coders: string[]; needed: string }
  | { state: 'stale_codings'; needed: string }
  | {
      state: 'computed'
      coders: string[]
      rows: number
      pooled_kappa: number | null
      per_function_kappa: Record<string, number | null>
      status: { overall: 'categories' | 'provisional'; functions: Record<string, 'categories' | 'provisional'> }
    }

export interface Dm1Item {
  artifact: string
  state: string
  provided: boolean
  detail: unknown
}

export interface Dm1Status {
  season: number
  items: Dm1Item[]
  inputs_ready: boolean
  note: string
  done_means: {
    done_means: 'DM1'
    met: boolean
    missing_records: string[]
    within_5_days: boolean | null
    elapsed_hours: number | null
    blocked_on: string[]
  }
}

export interface WriteAccess {
  writes_enabled: boolean
  token_accepted: boolean
}
