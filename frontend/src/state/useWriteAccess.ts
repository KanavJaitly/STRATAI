import { useEffect } from 'react'

import { useSession } from './session'

/** Ask for the write-access check (once; again when the token changes). `enabled` false asks nothing, for a component
 * that knows the check cannot help (a signed-in non-administrator cannot enter the platform write token). */
export function useWriteAccess(enabled = true): void {
  const { requestAccess } = useSession()
  useEffect(() => {
    if (enabled) requestAccess()
  }, [enabled, requestAccess])
}
