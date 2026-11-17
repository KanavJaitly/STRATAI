// Each team's branding (its logo), looked up by the signed-in team's number. This is a per-team setting, not a
// hardcoded header: another team using StratAI adds its own entry and files under public/teams/<number>/, and the
// header shows the field mark for a team without one. It lives here until the API's team settings carry a logo.

export interface TeamLogo {
  /** 1x image, 20 px tall (the height of the STRATAI wordmark line), plus sharper copies for denser screens. */
  src: string
  srcSet: string
  width: number
  height: number
  alt: string
}

export interface TeamBranding {
  logo: TeamLogo
}

const BRANDING: Record<number, TeamBranding> = {
  11: {
    logo: {
      src: '/teams/11/logo-20.png',
      srcSet: '/teams/11/logo-20.png 1x, /teams/11/logo-40.png 2x, /teams/11/logo-60.png 3x',
      width: 26,
      height: 20,
      alt: 'MORT logo',
    },
  },
}

export function teamBranding(teamNumber: number | null | undefined): TeamBranding | undefined {
  return teamNumber == null ? undefined : BRANDING[teamNumber]
}
