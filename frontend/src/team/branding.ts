// Each team's branding (its logo), looked up by the signed-in team's number. This is a per-team setting, not a
// hardcoded header: another team using StratAI adds its own entry and files under public/teams/<number>/, and the
// header shows the field mark for a team without one. It lives here until the API's team settings carry a logo.

export interface TeamLogo {
  /** 1x image, 24 px tall (checked on a phone: the detail holds at 24, not at 20), plus sharper copies for denser screens. */
  src: string
  srcSet: string
  width: number
  height: number
  alt: string
}

export interface TeamBranding {
  logo: TeamLogo
  /** Square copies of the logo for the browser tab, 32 px and 64 px (a sharp screen draws the tab icon at 32 px). */
  tabIcon: { src32: string; src64: string }
}

/** The tab icon when no team logo applies (signed out, or a team without one): the red/blue field mark. */
export const DEFAULT_TAB_ICON = '/favicon.svg'

const BRANDING: Record<number, TeamBranding> = {
  11: {
    logo: {
      src: '/teams/11/logo-24.png',
      srcSet: '/teams/11/logo-24.png 1x, /teams/11/logo-48.png 2x, /teams/11/logo-72.png 3x',
      width: 31,
      height: 24,
      alt: 'MORT logo',
    },
    tabIcon: { src32: '/teams/11/icon-32.png', src64: '/teams/11/icon-64.png' },
  },
}

export function teamBranding(teamNumber: number | null | undefined): TeamBranding | undefined {
  return teamNumber == null ? undefined : BRANDING[teamNumber]
}
