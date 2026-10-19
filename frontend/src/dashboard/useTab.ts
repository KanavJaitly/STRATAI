import { useSearchParams } from 'react-router-dom'

export interface TabDef { id: string; label: string }

/** The active tab is the `tab` URL parameter (default: the first). Arrow keys move between tabs (ARIA tabs). */
export function useTab(tabs: TabDef[]): [string, (id: string) => void] {
  const [params, setParams] = useSearchParams()
  const requested = params.get('tab')
  const active = tabs.some((t) => t.id === requested) ? requested! : tabs[0].id
  const select = (id: string) => {
    const next = new URLSearchParams(params)
    if (id === tabs[0].id) next.delete('tab')
    else next.set('tab', id)
    setParams(next, { replace: true }) // switching tabs is not a navigation; Back leaves the page
  }
  return [active, select]
}
