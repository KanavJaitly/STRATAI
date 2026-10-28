import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { axeViolations, renderAt } from '../../test/dashboard'
import { EVENT, MATCHES, METRICS, RED, STRENGTH } from '../../test/dashboardFixtures'
import { apiError, mockApi } from '../../test/mockApi'
import { TeamPage } from './TeamPage'

const PATTERN = '/events/:eventKey/teams/:team'
const TEAM = RED[0]

describe('TeamPage (P8-M3)', () => {
  it('shows strength, history and stored metrics from their own routes, with absences and the INTERIM caveat', async () => {
    mockApi({ [`GET /teams/${TEAM}/events/${EVENT}/strength`]: STRENGTH, [`GET /teams/${TEAM}/events/${EVENT}/metrics`]: METRICS,
      [`GET /events/${EVENT}/matches`]: MATCHES })
    const { container } = renderAt(PATTERN, `/events/${EVENT}/teams/${TEAM}`, <TeamPage />)
    expect(await screen.findByRole('heading', { name: 'Strength' })).toBeInTheDocument()
    expect(screen.getAllByText(/too few observations: fewer than 2 scouting observations/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/estimate/).length).toBeGreaterThan(0)
    expect(await screen.findByRole('heading', { name: 'Performance history at this event' })).toBeInTheDocument()
    expect(screen.getByText(/1 played: 1 won, 0 tied, 0 lost/)).toBeInTheDocument()
    expect(screen.getByText(/1 without a result at this moment/)).toBeInTheDocument()
    // the chart plots the alliance's score only for the played match
    const chart = screen.getByRole('img', { name: /Alliance score in each match/ })
    expect(chart).toHaveAccessibleName(/1 value in points.*1 missing/)
    expect(await screen.findByRole('heading', { name: /Stored metrics/ })).toBeInTheDocument()
    expect(screen.getByText(/including matches after any moment chosen above/)).toBeInTheDocument()
    expect(await axeViolations(container)).toEqual([])
  })

  it('labels the season auto-points chart and lists a missing event as missing', async () => {
    mockApi({ [`GET /teams/${TEAM}/events/${EVENT}/strength`]: STRENGTH, [`GET /teams/${TEAM}/events/${EVENT}/metrics`]: METRICS,
      [`GET /events/${EVENT}/matches`]: MATCHES })
    renderAt(PATTERN, `/events/${EVENT}/teams/${TEAM}`, <TeamPage />)
    const figure = (await screen.findByText('Average auto points by event this season')).closest('figure') as HTMLElement
    expect(within(figure).getByText(/missing \(no_matches_with_a_score_breakdown_before_as_of\)/)).toBeInTheDocument()
  })

  it('shows each part\'s own refusal independently', async () => {
    mockApi({ [`GET /teams/${TEAM}/events/${EVENT}/strength`]: apiError(404, 'epa_source_not_loaded', 'not loaded'),
      [`GET /teams/${TEAM}/events/${EVENT}/metrics`]: apiError(404, 'metrics_not_computed', 'not computed'),
      [`GET /events/${EVENT}/matches`]: MATCHES })
    renderAt(PATTERN, `/events/${EVENT}/teams/${TEAM}`, <TeamPage />)
    expect(await screen.findByText(/EPA source not loaded/)).toBeInTheDocument()
    expect(await screen.findByText(/Metrics not computed yet/)).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Performance history at this event' })).toBeInTheDocument()
  })

  it('rejects a non-numeric team without calling the API', () => {
    const api = mockApi({})
    renderAt(PATTERN, `/events/${EVENT}/teams/abc`, <TeamPage />)
    expect(screen.getByRole('heading', { name: 'Team not found' })).toBeInTheDocument()
    expect(api.calls.filter((c) => !c.path.startsWith('/human-inputs'))).toHaveLength(0)
  })

  it('counts a played match without a recorded winner separately, never as a loss', async () => {
    const noWinner = { ...MATCHES, matches: [{ ...MATCHES.matches[0], result: { score_red: 50, score_blue: 50, winning_alliance: null } }] }
    mockApi({ [`GET /teams/${TEAM}/events/${EVENT}/strength`]: STRENGTH, [`GET /teams/${TEAM}/events/${EVENT}/metrics`]: METRICS,
      [`GET /events/${EVENT}/matches`]: noWinner })
    renderAt(PATTERN, `/events/${EVENT}/teams/${TEAM}`, <TeamPage />)
    expect(await screen.findByText(/1 played: 0 won, 0 tied, 0 lost/)).toBeInTheDocument()
    expect(screen.getByText(/1 without a recorded winner/)).toBeInTheDocument()
  })
})
