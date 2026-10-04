// Conversions between the human-review editors' form rows and the artifact payloads the server validates
// (Codebook, Coding, ActionFunctionMap, Rubric). Blank numeric fields are omitted, so the server's model names
// them; nothing is defaulted here.

import type {
  ActionMapPayload, Artifact, ArtifactKind, ArtifactStatus, ArchetypeRule, CodebookPayload, KappaStatus, RubricPayload,
} from '../api/types'

export type FunctionRow = { function: string; family: string }
export type ArchetypeRow = {
  archetype: string; tier: string; priority: string; min_budget_usd: string
  manufacturing: string; programming: string; mentoring: string; achievable_features: string
}

export function codebookPayload(version: string, rows: FunctionRow[]): CodebookPayload {
  const functions: Record<string, string> = {}
  for (const row of rows) if (row.function.trim()) functions[row.function.trim()] = row.family.trim()
  return { version: version.trim(), functions }
}

/** Every reference row is present, an empty list meaning "no function" (the server requires all rows). */
export function codingPayload(rowIds: number[], checked: Record<number, Set<string>>): { labels: Record<string, string[]> } {
  const labels: Record<string, string[]> = {}
  for (const id of rowIds) labels[String(id)] = [...(checked[id] ?? new Set<string>())].sort()
  return { labels }
}

export function actionMapPayload(version: string, mapping: Record<string, Set<string>>): ActionMapPayload {
  const out: Record<string, string[]> = {}
  for (const [type, functions] of Object.entries(mapping)) if (type.trim()) out[type.trim()] = [...functions].sort()
  return { version: version.trim(), mapping: out }
}

const optionalNumber = (s: string): number | undefined => (s.trim() === '' ? undefined : Number(s))

export function rubricPayload(version: string, rows: ArchetypeRow[]): RubricPayload {
  return JSON.parse(JSON.stringify({
    version: version.trim(),
    archetypes: rows.map((r) => {
      const min_levels: ArchetypeRule['min_levels'] = {}
      for (const c of ['manufacturing', 'programming', 'mentoring'] as const) {
        if (r[c] !== '') min_levels[c] = Number(r[c])
      }
      return {
        archetype: r.archetype.trim(), tier: optionalNumber(r.tier), priority: optionalNumber(r.priority),
        min_budget_usd: optionalNumber(r.min_budget_usd), min_levels,
        achievable_features: r.achievable_features.split(',').map((f) => f.trim()).filter(Boolean),
      }
    }),
  })) as RubricPayload
}

export type StageState = 'missing' | 'incomplete' | 'awaiting_sign_off' | 'established' | 'submitted' | 'recorded'
  | KappaStatus['state']

export interface Stage { key: string; title: string; state: StageState; detail: string }

const of = (artifacts: Artifact[], kind: ArtifactKind, status?: ArtifactStatus) =>
  artifacts.filter((a) => a.kind === kind && (status === undefined || a.status === status))

function signOff(artifacts: Artifact[], kind: ArtifactKind): { state: StageState; detail: string } {
  const established = of(artifacts, kind, 'established').at(-1)
  if (established) return { state: 'established', detail: `established by ${established.established_by} (v${established.version} by ${established.author})` }
  const pending = of(artifacts, kind, 'submitted')
  if (pending.length) return { state: 'awaiting_sign_off', detail: `${pending.length} submitted, none established` }
  return { state: 'missing', detail: 'nothing submitted' }
}

/** The DM1 review stages in order, each read from the stored artifacts. Nothing here marks anything done. */
export function reviewStages(artifacts: Artifact[], kappa: KappaStatus | null): Stage[] {
  const coders = [...new Set(of(artifacts, 'coding', 'submitted').map((a) => a.author))]
  const reviews = of(artifacts, 'mentor_review', 'submitted')
  const kappaDetail = !kappa ? 'not loaded'
    : kappa.state === 'computed' ? `pooled κ ${kappa.pooled_kappa === null ? 'undefined' : kappa.pooled_kappa.toFixed(3)}; labels ${kappa.status.overall}`
      : kappa.needed
  return [
    { key: 'codebook', title: 'Codebook', ...signOff(artifacts, 'codebook') },
    { key: 'coding', title: 'Two independent codings',
      state: coders.length >= 2 ? 'submitted' : 'incomplete', detail: `${coders.length} of 2 coders${coders.length ? `: ${coders.join(', ')}` : ''}` },
    { key: 'kappa', title: 'Codebook agreement (κ)', state: kappa?.state ?? 'awaiting_codings', detail: kappaDetail },
    { key: 'consensus_coding', title: 'Consensus coding', ...signOff(artifacts, 'consensus_coding') },
    { key: 'action_function_map', title: 'Action → function map', ...signOff(artifacts, 'action_function_map') },
    { key: 'rubric', title: 'Feasibility rubric', ...signOff(artifacts, 'rubric') },
    { key: 'mentor_review', title: 'Mentor review', state: reviews.length ? 'recorded' : 'missing',
      detail: reviews.length ? `by ${reviews.at(-1)!.author}` : 'nothing recorded' },
  ]
}
