import { readState, stop } from './servers'

export default async function globalTeardown(): Promise<void> {
  for (const pid of Object.values(readState().pids)) stop(pid)
}
