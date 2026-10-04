import { describe, expect, it } from 'vitest'

import type { Artifact } from '../api/types'
import { payloadFrom } from './profileForm'
import { codingPayload, reviewStages, rubricPayload } from './reviewForms'
import { emptyAction, emptySpecForm, fromSpecJson, toSpecJson, type SpecForm } from './specForm'

const fullForm: SpecForm = {
  game_name: 'Synthetic Game', manual_title: 'Synthetic Manual', manual_version: 'v1',
  auto_seconds: '15', teleop_seconds: '135', endgame_seconds: '20',
  scoring_actions: [{ action_id: 'a1', name: 'Score', period: 'teleop', points: '2', unit: 'piece', field_element_id: 'goal',
    action_type: 'score_piece', manual_section: '6.4' }],
  ranking_point_rules: [{ rule_id: 'rp1', description: 'Bonus', ranking_points: '1', manual_section: '7.1' }],
  field_elements: [{ element_id: 'goal', name: 'Goal', count: '2', element_type: 'goal', manual_section: '5.2' }],
}

describe('structured spec form', () => {
  it('omits blank fields instead of defaulting them', () => {
    const spec = toSpecJson({ ...emptySpecForm(), game_name: 'Only a name', scoring_actions: [emptyAction()] })
    expect(spec.game_name).toBe('Only a name')
    expect(spec.match_length).toEqual({})
    expect(spec.scoring_actions).toEqual([{ field_element_id: null }])
  })

  it('never sends the fields the server owns', () => {
    const spec = toSpecJson(fullForm) as unknown as Record<string, unknown>
    expect(spec).not.toHaveProperty('season')
    expect(spec.source).toEqual({ manual_title: 'Synthetic Manual', manual_version: 'v1' })
  })

  it('round-trips a stored version back into the editor', () => {
    expect(fromSpecJson(toSpecJson(fullForm) as unknown as Record<string, unknown>)).toEqual(fullForm)
    expect(toSpecJson(fullForm).scoring_actions[0].points).toBe(2)
  })
})

describe('profile and review payloads', () => {
  it('sends a blank capability as missing so the server names it', () => {
    const payload = payloadFrom({ team_number: '', budget_usd: '', manufacturing: '2', programming: '1', mentoring: '', notes: '' })
    expect(payload).toEqual({ team_number: null, manufacturing: 2, programming: 1, notes: '' })
  })

  it('codes every reference row, an unchecked row as an empty list', () => {
    expect(codingPayload([1, 2, 3], { 2: new Set(['b', 'a']) })).toEqual({ labels: { 1: [], 2: ['a', 'b'], 3: [] } })
  })

  it('keeps only the minimum levels a rubric row sets', () => {
    const rubric = rubricPayload('r1', [{ archetype: 'X', tier: '2', priority: '1', min_budget_usd: '', manufacturing: '2',
      programming: '', mentoring: '0', achievable_features: 'a, b,' }])
    expect(rubric.archetypes[0]).toEqual({ archetype: 'X', tier: 2, priority: 1, min_levels: { manufacturing: 2, mentoring: 0 },
      achievable_features: ['a', 'b'] })
  })

  it('reads review stages from the stored artifacts and never marks anything done by itself', () => {
    const artifact = (kind: Artifact['kind'], author: string, status: Artifact['status']): Artifact => ({
      id: 1, kind, season: 2099, author, version: 1, payload: {}, payload_sha256: 'x', status, created_at: '',
      established_by: status === 'established' ? 'Mentor' : null, established_at: null, note: null })
    const stages = Object.fromEntries(reviewStages([
      artifact('codebook', 'A', 'established'), artifact('coding', 'A', 'submitted'), artifact('rubric', 'B', 'submitted'),
    ], null).map((s) => [s.key, s.state]))
    expect(stages).toEqual({ codebook: 'established', coding: 'incomplete', kappa: 'awaiting_codings',
      consensus_coding: 'missing', action_function_map: 'missing', rubric: 'awaiting_sign_off', mentor_review: 'missing' })
  })
})
