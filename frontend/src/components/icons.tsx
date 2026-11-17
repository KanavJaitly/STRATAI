// The app's one icon set: 24-unit line icons, drawn at 18 px with a 1.5 stroke in the current text colour (.icon in
// styles/app.css). Decorative by default: every icon sits next to a word that names the action.

type IconName = 'events' | 'team' | 'drive' | 'scouting' | 'admin' | 'chevron-down' | 'arrow-left' | 'arrow-right' | 'arrow-up'
  | 'arrow-down' | 'check' | 'grip' | 'info'

const PATHS: Record<IconName, string> = {
  events: 'M4 6.5A2 2 0 0 1 6 4.5h12a2 2 0 0 1 2 2V19a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM4 9.5h16M8.5 2.5v4M15.5 2.5v4',
  team: 'M9 11.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20c0-3.3 2.9-5.5 6.5-5.5s6.5 2.2 6.5 5.5M16 4.7a3.5 3.5 0 0 1 0 6.6M18 14.8c2 .7 3.5 2.4 3.5 5.2',
  drive: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM3.3 10.2l6.3 1.3M20.7 10.2l-6.3 1.3M12 14.5V21',
  scouting: 'M8 4.5H6.5a2 2 0 0 0-2 2V19a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V6.5a2 2 0 0 0-2-2H16M9 3h6v3H9zM8.5 11h7M8.5 15h4.5',
  admin: 'M4 7h9M17 7h3M4 17h3M11 17h9M15 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM9 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  'chevron-down': 'M6 9l6 6 6-6',
  'arrow-left': 'M19 12H5M11 6l-6 6 6 6',
  'arrow-right': 'M5 12h14M13 6l6 6-6 6',
  'arrow-up': 'M12 19V5M6 11l6-6 6 6',
  'arrow-down': 'M12 5v14M6 13l6 6 6-6',
  check: 'M5 12.5l4.5 4.5L19 7',
  grip: 'M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 7.6v.4',
}

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg className={className ? `icon ${className}` : 'icon'} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} />
    </svg>
  )
}

/** The StratAI mark: the field seen from above, red alliance on the left and blue on the right. */
export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 22 10" aria-hidden="true" focusable="false">
      <rect x="0" y="0" width="10" height="10" rx="2" fill="var(--red)" />
      <rect x="12" y="0" width="10" height="10" rx="2" fill="var(--blue)" />
    </svg>
  )
}
