import { useEffect, useState } from 'react'

import { getCountdown } from '../../lib/api'
import type { Timestep } from '../../types/contracts'

/** Facilities cut off and expected to be cut off at one timestep; null until loaded. */
export type CountdownPoint = { cutOff: number; expected: number } | null

/**
 * The countdown's two counts for every timestep, for the timeline sparkline. Loaded once, in the
 * API's low-priority lane (never ahead of the current step's data), from the shared GET memo.
 */
export function useCountdownSeries(timesteps: readonly Timestep[]): CountdownPoint[] {
  const [series, setSeries] = useState<{ key: string; points: CountdownPoint[] }>({ key: '', points: [] })
  const key = timesteps.join()
  useEffect(() => {
    let cancelled = false
    timesteps.forEach((ts, i) => {
      getCountdown(ts, 'series').then(
        (c) => {
          if (cancelled) return
          setSeries((s) => {
            const points = s.key === key ? [...s.points] : timesteps.map(() => null)
            points[i] = { cutOff: c.cut_off.length, expected: c.expected.length }
            return { key, points }
          })
        },
        () => {}, // a missing point leaves a gap in the sparkline
      )
    })
    return () => {
      cancelled = true
    }
  }, [key, timesteps])
  return series.key === key ? series.points : timesteps.map(() => null)
}
