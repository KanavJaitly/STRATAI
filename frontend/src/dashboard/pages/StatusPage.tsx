import { dashboardApi } from '../../api/dashboard'
import { API_BASE } from '../../api/client'
import { useSession } from '../../state/session'
import { useResource } from '../../components/useResource'
import { PageHeader } from '../common'
import { ResourceView } from '../display'

/** System status (P8-M1 (g)): liveness and readiness exactly as the probes report them. */
export function StatusPage() {
  const health = useResource((signal) => dashboardApi.health(signal), 'health')
  const ready = useResource((signal) => dashboardApi.ready(signal), 'ready')
  const { access } = useSession()
  return (
    <>
      <PageHeader title="System status" subtitle={<>The API at <code>{API_BASE}</code>, as its own probes report it.</>} />
      <section className="card" aria-labelledby="liveness">
        <h2 id="liveness">Liveness</h2>
        <ResourceView resource={health} what="liveness">
          {(h) => <p><span className={`badge badge-${h.status === 'ok' ? 'ok' : 'warn'}`}>{h.status}</span> <span className="muted small">environment {h.env}</span></p>}
        </ResourceView>
      </section>
      <section className="card" aria-labelledby="readiness">
        <h2 id="readiness">Readiness</h2>
        <ResourceView resource={ready} what="readiness">
          {(r) => (
            <>
              <p><span className={`badge badge-${r.status === 'ready' ? 'ok' : 'bad'}`}>{r.status}</span></p>
              <dl className="facts">
                {Object.entries(r.checks).map(([name, value]) => <div key={name} className="fact-row"><dt>{name}</dt><dd>{value}</dd></div>)}
              </dl>
            </>
          )}
        </ResourceView>
      </section>
      <section className="card" aria-labelledby="writes">
        <h2 id="writes">Writes</h2>
        <p>{access ? (access.writes_enabled ? (access.token_accepted ? 'Write token accepted.' : 'Writes enabled on the server; no valid token entered.') : 'Writes are disabled on this server.') : 'Write access unknown (the API did not answer).'}</p>
      </section>
      <section className="card" aria-labelledby="about">
        <h2 id="about">What the dashboard can show here</h2>
        <p>Readiness checks only the database. Each view reports separately whether its model or data source is loaded:
          a result that needs a model that is not pinned on this server shows <code>model_not_loaded</code>, and the
          alliance-selection pick list shows <code>not_approved</code> until the season rules are approved.
          Nothing is substituted for a missing result.</p>
      </section>
    </>
  )
}
