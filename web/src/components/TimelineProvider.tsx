import { type ReactNode, useEffect, useState } from 'react'

import { getTimesteps } from '../lib/api'
import {
  buildTimeline,
  FALLBACK_TIMELINE,
  sameTimeline,
  TimelineContext,
} from '../lib/timeline'

/**
 * Serves the computed fallback timeline at once, then checks it against /api/hazard/timesteps:
 * if they differ, the API wins (with a console warning). A failed request keeps the fallback.
 */
export default function TimelineProvider({ children }: { children: ReactNode }) {
  const [timeline, setTimeline] = useState(FALLBACK_TIMELINE)
  useEffect(() => {
    let cancelled = false
    getTimesteps().then(
      (api) => {
        if (cancelled || sameTimeline(FALLBACK_TIMELINE, api)) return
        console.warn(
          'Replay timeline from /api/hazard/timesteps differs from the built-in fallback; using the API.',
          api,
        )
        setTimeline(buildTimeline(api.timesteps, api.landfall))
      },
      (err: unknown) => {
        if (!cancelled) console.warn('Could not load /api/hazard/timesteps; using the fallback.', err)
      },
    )
    return () => {
      cancelled = true
    }
  }, [])
  return <TimelineContext value={timeline}>{children}</TimelineContext>
}
