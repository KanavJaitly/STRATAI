// One team's matches at one event, as served by GET /events/{event_key}/matches: its own alliance's score in each, and
// its won / tied / lost record. Shared by the team page and the live draft page's team profile so they never disagree.

import type { EventMatchesResponse } from '../api/generated'
import type { ChartPoint } from './charts'
import { matchLabel } from './routing'

export type ServedMatch = EventMatchesResponse['matches'][number]

export interface TeamResults {
  /** Every match the team is scheduled in at this moment, in served order. */
  mine: ServedMatch[]
  /** The ones with a result at this moment. */
  played: ServedMatch[]
  wins: number
  ties: number
  losses: number
  /** A result without a recorded winner is not a loss. */
  noWinner: number
  /** The team's own alliance's score in each match (missing when it has no result yet). */
  points: ChartPoint[]
}

export function ownColour(match: ServedMatch, team: number): 'red' | 'blue' {
  return match.red_team_numbers.includes(team) ? 'red' : 'blue'
}

export function teamResults(data: EventMatchesResponse, team: number): TeamResults {
  const mine = data.matches.filter((m) => m.red_team_numbers.includes(team) || m.blue_team_numbers.includes(team))
  const points: ChartPoint[] = mine.map((m) => {
    const red = ownColour(m, team) === 'red'
    return {
      label: matchLabel(m),
      value: m.result ? (red ? m.result.score_red : m.result.score_blue) : null,
      note: m.result_withheld_reason?.replaceAll('_', ' '),
      tone: red ? 'red' : 'blue',
    }
  })
  const played = mine.filter((m) => m.result)
  const wins = played.filter((m) => m.result?.winning_alliance === ownColour(m, team)).length
  const ties = played.filter((m) => m.result?.winning_alliance === 'tie').length
  const losses = played.filter((m) => m.result?.winning_alliance === (ownColour(m, team) === 'red' ? 'blue' : 'red'))
    .length
  return { mine, played, wins, ties, losses, noWinner: played.length - wins - ties - losses, points }
}

/** W, L or T for the team in one played match ('–' when no winner is recorded). */
export function outcome(match: ServedMatch, team: number): 'W' | 'L' | 'T' | '–' {
  const winner = match.result?.winning_alliance
  if (!winner) return '–'
  if (winner === 'tie') return 'T'
  return winner === ownColour(match, team) ? 'W' : 'L'
}
