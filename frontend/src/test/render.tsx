import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'

import { SessionProvider } from '../state/session'

/** Renders a page as a named person ("Test Person") for season 2099, a synthetic season no real data uses. */
export function renderPage(page: ReactElement, { actor = 'Test Person', season = 2099 } = {}) {
  window.localStorage.setItem('stratai.actor', actor)
  window.localStorage.setItem('stratai.season', String(season))
  return render(
    <SessionProvider>
      <MemoryRouter>{page}</MemoryRouter>
    </SessionProvider>,
  )
}
