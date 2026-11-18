// "Our team": the signed-in member's own team number (MORT, 11), marked wherever a team appears so the team can find
// itself at a glance: a gold rail on its row and a gold diamond after its number (OursMark). Display only.

import { useAuth } from '../auth/authState'

export function useOurTeam(): number | null {
  const { session } = useAuth()
  return session.workspace?.team_number ?? null
}

/** The row class for a team's table row: our team's row gets the gold rail. */
export function ourRowClass(team: number, ours: number | null): string | undefined {
  return ours !== null && team === ours ? 'row-ours' : undefined
}
