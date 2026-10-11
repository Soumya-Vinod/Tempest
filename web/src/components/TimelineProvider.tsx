import { type ReactNode, useEffect, useState } from 'react'

import { getApiStatus, getTimesteps, subscribeApiStatus } from '../lib/api'
import {
  buildTimeline,
  FALLBACK_TIMELINE,
  sameTimeline,
  TimelineContext,
} from '../lib/timeline'

/** Longest the check waits for the request queue to go idle. */
const CHECK_AFTER_MS = 15_000

/** Resolves once the API request queue has been busy and is idle again (or after `maxMs`). */
function whenQueueIdle(maxMs: number): { promise: Promise<void>; cancel: () => void } {
  let cancel = () => {}
  const promise = new Promise<void>((resolve) => {
    let seenBusy = getApiStatus().busy
    const done = () => {
      unsubscribe()
      window.clearTimeout(timer)
      resolve()
    }
    const unsubscribe = subscribeApiStatus(() => {
      if (getApiStatus().busy) seenBusy = true
      else if (seenBusy) done()
    })
    const timer = window.setTimeout(done, maxMs)
    cancel = () => {
      unsubscribe()
      window.clearTimeout(timer)
    }
  })
  return { promise, cancel }
}

/**
 * Serves the computed fallback timeline at once, then checks it against /api/hazard/timesteps:
 * if they differ, the API wins (with a console warning). A failed request keeps the fallback.
 * The check waits until the first burst of requests is done, so it never takes one of the
 * request queue's slots on load.
 */
export default function TimelineProvider({ children }: { children: ReactNode }) {
  const [timeline, setTimeline] = useState(FALLBACK_TIMELINE)
  useEffect(() => {
    let cancelled = false
    const idle = whenQueueIdle(CHECK_AFTER_MS)
    idle.promise
      .then(() => getTimesteps())
      .then(
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
      idle.cancel()
    }
  }, [])
  return <TimelineContext value={timeline}>{children}</TimelineContext>
}
