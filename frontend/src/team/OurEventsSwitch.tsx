import type { TeamEvents } from '../auth/api'

const STATUS: Record<string, string> = { happening: 'now', upcoming: 'next', past: 'done' }

/** The team's events as one-tap choices (the chosen one pressed, the current one marked). Renders nothing when the
 * team has not listed any events. */
export function OurEventsSwitch({ events, value, onChange, label = 'Our events' }: { events: TeamEvents; value: string;
  onChange: (eventKey: string) => void; label?: string }) {
  if (events.team_events.length === 0) return null
  return (
    <div className="our-events" role="group" aria-label={label}>
      {events.team_events.map((e) => (
        <button key={e.event_key} type="button" className="our-event" aria-pressed={e.event_key === value}
          onClick={() => onChange(e.event_key)}>
          <span className="our-event-name">{e.name ?? e.event_key}</span>
          <span className="our-event-meta">
            {e.event_key === events.current_event_key ? 'Current' : e.status ? STATUS[e.status] : ''}
          </span>
        </button>
      ))}
    </div>
  )
}
