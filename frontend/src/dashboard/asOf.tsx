// The moment a view is taken at (`as_of`) lives in the URL (P8-Q9), so a view is shareable and back/forward works.
// It is entered as local date-time and sent as an ISO-8601 instant (P8-Q11). The server refuses a future moment
// (P7-D4); that refusal is shown as-is rather than prevented here, so the server stays the one authority.

import { useState, type FormEvent } from 'react'

import { When } from './display'
import { isoToLocalInput, localInputToIso, useAsOf } from './asOfParams'

export function AsOfControl({ label = 'Moment (as of)', defaultNote }: { label?: string; defaultNote: string }) {
  const [asOf, setAsOf] = useAsOf()
  const [draft, setDraft] = useState(isoToLocalInput(asOf))
  const [lastAsOf, setLastAsOf] = useState(asOf)
  if (asOf !== lastAsOf) { // the URL changed (back/forward or a link): show its moment
    setLastAsOf(asOf)
    setDraft(isoToLocalInput(asOf))
  }
  const apply = (event: FormEvent) => {
    event.preventDefault()
    if (draft === isoToLocalInput(asOf)) return // unchanged: keep the URL's exact moment
    setAsOf(localInputToIso(draft))
  }
  return (
    <form className="as-of" onSubmit={apply} aria-label="Moment">
      <label>
        {label}
        <input type="datetime-local" step={1} value={draft} onChange={(e) => setDraft(e.target.value)} />
      </label>
      <button type="submit" className="secondary">Apply</button>
      {asOf && <button type="button" className="link" onClick={() => { setDraft(''); setAsOf(null) }}>Use default</button>}
      <span className="small muted">
        {asOf ? <>Showing <When value={asOf} /></> : defaultNote}
      </span>
    </form>
  )
}
