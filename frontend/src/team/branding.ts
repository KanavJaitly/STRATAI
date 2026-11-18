// Each team's branding (its logo), looked up by the signed-in team's number. StratAI is set up for MORT (Team 11), so
// MORT's branding is the default: signed out (the login page) and for any team without its own entry. Another team
// using StratAI adds its own entry and files under public/teams/<number>/ and gets its logo once signed in. It lives
// here until the API's team settings carry a logo.

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
  /** Square tab icons, 32 px and a larger one for sharp screens (only used for a team other than the default: the
   * default team's icons are index.html's favicons). */
  tabIcon: { src32: string; src64: string }
}

/** The team whose branding is the default (index.html's favicons are its icons too). */
export const DEFAULT_TEAM = 11

const BRANDING: Record<number, TeamBranding> = {
  11: {
    logo: {
      src: '/teams/11/logo-24.png',
      srcSet: '/teams/11/logo-24.png 1x, /teams/11/logo-48.png 2x, /teams/11/logo-72.png 3x',
      width: 31,
      height: 24,
      alt: 'MORT logo',
    },
    tabIcon: { src32: '/favicon-32.png', src64: '/favicon-48.png' },
  },
}

/** The branding for a team: its own entry, else the default team's (MORT). Never undefined. */
export function teamBranding(teamNumber: number | null | undefined): TeamBranding {
  return (teamNumber == null ? undefined : BRANDING[teamNumber]) ?? BRANDING[DEFAULT_TEAM]
}

/** Whether a team has branding of its own that differs from the default (so the tab icon should change). */
export function hasOwnBranding(teamNumber: number | null | undefined): boolean {
  return teamNumber != null && teamNumber !== DEFAULT_TEAM && teamNumber in BRANDING
}
