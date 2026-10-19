// Test helpers for dashboard pages: render a page at a URL with the app's own route patterns, and run axe.

import { render } from '@testing-library/react'
import axe from 'axe-core'
import { useEffect, type ReactElement } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

import { SessionProvider } from '../state/session'

const probe = { url: '' }

function LocationProbe() {
  const location = useLocation()
  useEffect(() => { probe.url = location.pathname + location.search })
  return null
}

/** The current URL inside the test router (path + query), after any navigation the page made. */
export function currentUrl(): string {
  return probe.url
}

/** Renders `element` at `url`, matched by `pattern` (the same pattern App.tsx uses), as a named person. */
export function renderAt(pattern: string, url: string, element: ReactElement, { actor = 'Test Person' } = {}) {
  window.localStorage.setItem('stratai.actor', actor)
  return render(
    <SessionProvider>
      <MemoryRouter initialEntries={[url]}>
        <LocationProbe />
        <Routes>
          <Route path={pattern} element={element} />
        </Routes>
      </MemoryRouter>
    </SessionProvider>,
  )
}

/**
 * Runs axe on a rendered container (P8-M7). In jsdom, colour contrast cannot be computed (no layout or computed
 * colours), so that rule is checked by reviewing the design tokens instead. `region` needs the app shell's
 * landmarks, which a page rendered alone does not have, so it is checked in the shell test.
 */
export async function axeViolations(container: Element, { region = false } = {}): Promise<string[]> {
  const result = await axe.run(container, {
    rules: { 'color-contrast': { enabled: false }, region: { enabled: region } },
  })
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length} node(s): ${v.nodes.slice(0, 2).map((n) => n.html).join(' | ')})`)
}
