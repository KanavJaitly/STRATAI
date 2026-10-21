import { useState } from 'react'

import { dashboardApi } from '../api/dashboard'
import type { BriefingResponse } from '../api/generated'
import { useResource } from '../components/useResource'
import { fallbackText, modelWasCalled } from './briefingText'
import { ResourceView, When } from './display'

/**
 * P9-M5: the readable briefing (GET /matches/{m}/briefing) beside the pre-match report.
 * - It is fetched only when asked for: building it rebuilds the whole report (P9-R7).
 * - It is requested with the report's own `as_of` parameter, so its moment is chosen the same way (the request time
 *   when none is given). If the moment it was taken at differs from the report's, the panel says so.
 * - Its mode is always labelled (P9-Q12): 'arranged by a language model' or 'fixed layout', with the reason the
 *   fixed layout was served, and whether a model was called at all. Every sentence is the report's facts in their
 *   fixed wording; a language model can only have chosen the grouping, the order and a label from a fixed list.
 * - Text is rendered as text, never as HTML.
 */
function ModeLine({ data }: { data: BriefingResponse }) {
  if (data.mode === 'llm') {
    return (
      <p className="small briefing-mode">
        <span className="badge badge-warn">arranged by a language model</span>{' '}
        {data.model ?? 'model unknown'} chose the grouping, the order and the topic labels; every fact is in its fixed
        wording.
      </p>
    )
  }
  return (
    <p className="small briefing-mode">
      <span className="badge badge-old">fixed layout</span>{' '}
      {modelWasCalled(data.fallback_reason) ? 'A language model was called, but its arrangement was not used: '
        : 'No language model was used: '}
      {fallbackText(data.fallback_reason)}{' '}
      {data.fallback_reason && <code className="reason-code">({data.fallback_reason})</code>}
    </p>
  )
}

function Briefing({ data, reportAsOf }: { data: BriefingResponse; reportAsOf: string }) {
  return (
    <div className="briefing">
      <ModeLine data={data} />
      {data.as_of !== reportAsOf && (
        <p className="notice notice-info small">This briefing was taken at <When value={data.as_of} />, the report
          above at <When value={reportAsOf} />. Reload the page to see both at the same moment.</p>
      )}
      {data.sections.map((section) => (
        <div key={section.heading} className="briefing-section">
          <h3>{section.heading}</h3>
          {section.sentences.map((sentence) => <p key={sentence.fact_ids.join(' ')}>{sentence.text}</p>)}
        </div>
      ))}
      <p className="small muted">{data.disclaimer}</p>
    </div>
  )
}

export function BriefingPanel({ matchKey, asOf, reportAsOf }: { matchKey: string; asOf: string | null;
  reportAsOf: string }) {
  const [open, setOpen] = useState(false)
  const briefing = useResource((s) => dashboardApi.briefing(matchKey, asOf, s), `briefing:${matchKey}:${asOf}`, open)
  return (
    <section className={`card${briefing.data ? '' : ' no-print'}`} aria-labelledby="briefing-heading">
      <h2 id="briefing-heading">Readable briefing</h2>
      <p className="small muted">This report as plain sentences, built from its facts. Every value, caveat and absence
        is stated in fixed wording; a language model, when one is used, only chooses the grouping, the order and a topic
        label from a fixed list.</p>
      {open
        ? <ResourceView resource={briefing} what="briefing" loadingText="Building the briefing (a few seconds)…">
          {(data) => <Briefing data={data} reportAsOf={reportAsOf} />}
        </ResourceView>
        : <button type="button" className="secondary" onClick={() => setOpen(true)}>Show the readable briefing</button>}
    </section>
  )
}
