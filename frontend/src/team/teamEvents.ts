// The team's events (Team > Settings > Our events) and its current event, for every member: the events page lists
// them first, and the dashboards offer them as one-tap choices and open on the current one.

import { useAuth } from '../auth/authState'
import { workspace, type TeamEvents } from '../auth/api'
import { useLoad } from '../components/common'

const NONE: TeamEvents = { team_events: [], pinned_event_key: null, current_event_key: null, current_reason: null }

/** The team's events; empty for anyone not signed in, or while loading or after an error (nothing depends on it). */
export function useTeamEvents(): TeamEvents & { loading: boolean } {
  const { signedIn, can } = useAuth()
  const allowed = signedIn && can('team_info')
  const loaded = useLoad(async () => (allowed ? workspace.teamEvents() : NONE), [allowed])
  return { ...(loaded.data ?? NONE), loading: loaded.loading }
}
