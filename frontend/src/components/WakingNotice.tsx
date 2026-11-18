import { useEffect, useState } from 'react'

/** Shown while a request is pending (render it only then): after a few seconds, says the server is waking up. The
 * hosted API sleeps after a quiet spell and its first answer can take up to a minute; a quick answer never shows this. */
export function WakingNotice({ after = 4000 }: { after?: number }) {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const timer = window.setTimeout(() => setSlow(true), after)
    return () => window.clearTimeout(timer)
  }, [after])
  if (!slow) return null
  return (
    <p className="notice notice-info waking" role="status">
      Waking up the server after a quiet spell. This can take up to a minute; it&apos;s quick after that.
    </p>
  )
}
