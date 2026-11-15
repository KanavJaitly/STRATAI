// Phase 11 follow-up: any team number on the live draft page opens that team's profile in an in-page drawer. The board
// provides this context; the team buttons call it with themselves as the element focus returns to on close.

import { createContext, useContext } from 'react'

export type OpenProfile = (team: number, trigger: HTMLElement | null) => void

export const ProfileContext = createContext<OpenProfile | null>(null)

export function useOpenProfile(): OpenProfile | null {
  return useContext(ProfileContext)
}

/** What the live page hands to the team page it navigates to (router state, never browser storage), and gets back from
 * its "Back to live alliance selection" link or the browser's back button. */
export interface LiveDraftReturn {
  liveDraft: { selected: number | null; scrollY: number }
}

export function readLiveDraftReturn(state: unknown): LiveDraftReturn['liveDraft'] | null {
  if (typeof state !== 'object' || state === null || !('liveDraft' in state)) return null
  const value = (state as { liveDraft: unknown }).liveDraft
  if (typeof value !== 'object' || value === null) return null
  const { selected, scrollY } = value as { selected?: unknown; scrollY?: unknown }
  return {
    selected: typeof selected === 'number' && Number.isInteger(selected) && selected > 0 ? selected : null,
    scrollY: typeof scrollY === 'number' && Number.isFinite(scrollY) && scrollY >= 0 ? scrollY : 0,
  }
}
