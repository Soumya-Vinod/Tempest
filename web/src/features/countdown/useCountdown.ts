import { useEffect, useState } from 'react'

import { ApiError, getCountdown } from '../../lib/api'
import type { ActionCountdown, KeyMoment, Timestep } from '../../types/contracts'

export type CountdownState =
  | { status: 'loading' }
  | { status: 'ok'; data: ActionCountdown }
  | { status: 'unavailable'; message: string } // 501: fixture not built
  | { status: 'error'; message: string }

// Small, precomputed responses: keep every timestep once loaded.
const cache = new Map<Timestep, Promise<ActionCountdown>>()

function load(timestep: Timestep): Promise<ActionCountdown> {
  let hit = cache.get(timestep)
  if (!hit) {
    hit = getCountdown(timestep)
    hit.catch(() => cache.delete(timestep))
    cache.set(timestep, hit)
  }
  return hit
}

/**
 * The action countdown for the selected timestep (v1.3), and the replay's key moments (the
 * same at every timestep, so the last loaded ones stay while the next timestep loads).
 */
export function useCountdown(timestep: Timestep): {
  state: CountdownState
  moments: KeyMoment[]
} {
  const [result, setResult] = useState<{ timestep: Timestep; state: CountdownState } | null>(
    null,
  )
  const [moments, setMoments] = useState<KeyMoment[]>([])

  useEffect(() => {
    let live = true
    load(timestep).then(
      (data) => {
        if (!live) return
        setResult({ timestep, state: { status: 'ok', data } })
        setMoments(data.key_moments)
      },
      (err: unknown) => {
        if (!live) return
        const message = err instanceof Error ? err.message : String(err)
        const state: CountdownState =
          err instanceof ApiError && err.status === 501
            ? { status: 'unavailable', message }
            : { status: 'error', message }
        setResult({ timestep, state })
      },
    )
    return () => {
      live = false
    }
  }, [timestep])

  const state: CountdownState =
    result && result.timestep === timestep ? result.state : { status: 'loading' }
  return { state, moments }
}
