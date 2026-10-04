// The structured-spec editor's form state, and its conversion to and from GameSpec JSON.
// - Every field is a string while it is being edited, so a half-entered draft can be saved. The server keeps
//   incomplete drafts together with their validation errors.
// - A blank field is left out of the JSON. That lets the server's GameSpec model name exactly what is missing,
//   rather than the page inventing a value.

import type { GameSpecDraft, Period } from '../api/types'

export interface ActionRow {
  action_id: string; name: string; period: Period | ''; points: string; unit: string
  field_element_id: string; action_type: string; manual_section: string
}
export interface RuleRow { rule_id: string; description: string; ranking_points: string; manual_section: string }
export interface ElementRow { element_id: string; name: string; count: string; element_type: string; manual_section: string }

export interface SpecForm {
  game_name: string
  manual_title: string
  manual_version: string
  auto_seconds: string
  teleop_seconds: string
  endgame_seconds: string
  scoring_actions: ActionRow[]
  ranking_point_rules: RuleRow[]
  field_elements: ElementRow[]
}

export const emptyAction = (): ActionRow => ({
  action_id: '', name: '', period: '', points: '', unit: '', field_element_id: '', action_type: '', manual_section: '',
})
export const emptyRule = (): RuleRow => ({ rule_id: '', description: '', ranking_points: '', manual_section: '' })
export const emptyElement = (): ElementRow => ({
  element_id: '', name: '', count: '', element_type: '', manual_section: '',
})

export function emptySpecForm(): SpecForm {
  return {
    game_name: '', manual_title: '', manual_version: '', auto_seconds: '', teleop_seconds: '', endgame_seconds: '',
    scoring_actions: [], ranking_point_rules: [], field_elements: [],
  }
}

function num(value: string): number | undefined {
  if (value.trim() === '') return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function text(value: string): string | undefined {
  return value.trim() === '' ? undefined : value.trim()
}

/** The JSON sent to the server. Blank fields are omitted, never defaulted. */
export function toSpecJson(form: SpecForm): GameSpecDraft {
  return JSON.parse(JSON.stringify({
    game_name: text(form.game_name),
    match_length: {
      auto_seconds: num(form.auto_seconds),
      teleop_seconds: num(form.teleop_seconds),
      endgame_seconds: num(form.endgame_seconds),
    },
    scoring_actions: form.scoring_actions.map((a) => ({
      action_id: text(a.action_id), name: text(a.name), period: a.period || undefined, points: num(a.points),
      unit: text(a.unit), field_element_id: text(a.field_element_id) ?? null, action_type: text(a.action_type),
      manual_section: text(a.manual_section),
    })),
    ranking_point_rules: form.ranking_point_rules.map((r) => ({
      rule_id: text(r.rule_id), description: text(r.description), ranking_points: num(r.ranking_points),
      manual_section: text(r.manual_section),
    })),
    field_elements: form.field_elements.map((e) => ({
      element_id: text(e.element_id), name: text(e.name), count: num(e.count), element_type: text(e.element_type),
      manual_section: text(e.manual_section),
    })),
    source: { manual_title: text(form.manual_title), manual_version: text(form.manual_version) },
  })) as GameSpecDraft
}

const str = (value: unknown): string => (value === undefined || value === null ? '' : String(value))

/** A stored version back into the editor, to start a new version from it. */
export function fromSpecJson(spec: Record<string, unknown>): SpecForm {
  const length = (spec.match_length ?? {}) as Record<string, unknown>
  const source = (spec.source ?? {}) as Record<string, unknown>
  const rows = (key: string) => (Array.isArray(spec[key]) ? (spec[key] as Record<string, unknown>[]) : [])
  return {
    game_name: str(spec.game_name),
    manual_title: str(source.manual_title),
    manual_version: str(source.manual_version),
    auto_seconds: str(length.auto_seconds),
    teleop_seconds: str(length.teleop_seconds),
    endgame_seconds: str(length.endgame_seconds),
    scoring_actions: rows('scoring_actions').map((a) => ({
      action_id: str(a.action_id), name: str(a.name), period: (str(a.period) as Period | ''), points: str(a.points),
      unit: str(a.unit), field_element_id: str(a.field_element_id), action_type: str(a.action_type),
      manual_section: str(a.manual_section),
    })),
    ranking_point_rules: rows('ranking_point_rules').map((r) => ({
      rule_id: str(r.rule_id), description: str(r.description), ranking_points: str(r.ranking_points),
      manual_section: str(r.manual_section),
    })),
    field_elements: rows('field_elements').map((e) => ({
      element_id: str(e.element_id), name: str(e.name), count: str(e.count), element_type: str(e.element_type),
      manual_section: str(e.manual_section),
    })),
  }
}
