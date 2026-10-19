// The engine's strategy representation rules, mirrored for the editor (the server still validates).

import type { RobotPlan, Strategy } from '../api/generated'

export type Component = 'auto' | 'teleop' | 'endgame'
export const COMPONENTS: Component[] = ['auto', 'teleop', 'endgame']

/** "No strategy specified": every robot scores every component, as history played it (the engine's baseline). */
export function baselineStrategy(teams: number[]): Strategy {
  const robots = teams.map((team_number): RobotPlan => ({ team_number, role: 'scoring', components: [...COMPONENTS] }))
  return { vocabulary: 'p6-strategy-v1', robots: robots as Strategy['robots'] }
}

/** Client-side checks mirroring the engine's representation rules; the server still validates (invalid_strategy). */
export function strategyProblems(strategy: Strategy, allies: number[], opponents: number[]): string[] {
  const problems: string[] = []
  for (const robot of strategy.robots) {
    const role = robot.role ?? 'scoring'
    const components = robot.components ?? COMPONENTS
    if (components.includes('teleop') && role !== 'scoring') {
      problems.push(`Team ${robot.team_number}: teleop scoring needs the scoring role.`)
    }
    if (role === 'defense' && (robot.defense_target == null || !opponents.includes(robot.defense_target))) {
      problems.push(`Team ${robot.team_number}: choose an opposing robot to defend.`)
    }
    if (role === 'feeding' && (robot.feed_target == null || !allies.includes(robot.feed_target) || robot.feed_target === robot.team_number)) {
      problems.push(`Team ${robot.team_number}: choose an ally to feed.`)
    }
  }
  return problems
}
