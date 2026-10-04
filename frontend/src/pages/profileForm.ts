import type { CapabilityPayload, Level } from '../api/types'

export const LEVELS: { value: Level; label: string }[] = [
  { value: 0, label: '0 · none' }, { value: 1, label: '1 · basic' },
  { value: 2, label: '2 · intermediate' }, { value: 3, label: '3 · advanced' },
]
export const CAPABILITIES = ['manufacturing', 'programming', 'mentoring'] as const

export interface ProfileForm {
  team_number: string; budget_usd: string; manufacturing: string; programming: string; mentoring: string; notes: string
}

export const blankForm = (): ProfileForm => ({
  team_number: '', budget_usd: '', manufacturing: '', programming: '', mentoring: '', notes: '',
})

export function formFrom(payload: CapabilityPayload): ProfileForm {
  return {
    team_number: payload.team_number === null ? '' : String(payload.team_number),
    budget_usd: String(payload.budget_usd), manufacturing: String(payload.manufacturing),
    programming: String(payload.programming), mentoring: String(payload.mentoring), notes: payload.notes,
  }
}

/** Blank fields are sent as missing, so the server's CapabilityIntake model names them; nothing is defaulted. */
export function payloadFrom(form: ProfileForm): CapabilityPayload {
  const value = (s: string) => (s.trim() === '' ? undefined : Number(s))
  return JSON.parse(JSON.stringify({
    team_number: form.team_number.trim() === '' ? null : Number(form.team_number),
    budget_usd: value(form.budget_usd), manufacturing: value(form.manufacturing),
    programming: value(form.programming), mentoring: value(form.mentoring), notes: form.notes,
  })) as CapabilityPayload
}
