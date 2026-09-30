import { useEffect, useState } from 'react'

import { ApiError, getCriticalLinks } from '../../lib/api'
import type { CriticalLinks, Horizon, Timestep } from '../../types/contracts'

export type CriticalLinksState =
  | { status: 'loading' }
  | { status: 'ok'; data: CriticalLinks }
  | { status: 'unavailable'; message: string } // 501: fixture not built
  | { status: 'error'; message: string }

// Small, precomputed responses: keep every timestep × horizon once loaded.
const cache = new Map<string, Promise<CriticalLinks>>()

function load(timestep: Timestep, horizon: Horizon): Promise<CriticalLinks> {
  const key = `${timestep}|${horizon}`
  let hit = cache.get(key)
  if (!hit) {
    hit = getCriticalLinks(timestep, horizon)
    hit.catch(() => cache.delete(key))
    cache.set(key, hit)
  }
  return hit
}

/** The critical links (v1.4) for the selected timestep and horizon. */
export function useCriticalLinks(timestep: Timestep, horizon: Horizon): CriticalLinksState {
  const key = `${timestep}|${horizon}`
  const [result, setResult] = useState<{ key: string; state: CriticalLinksState } | null>(null)

  useEffect(() => {
    let live = true
    load(timestep, horizon).then(
      (data) => live && setResult({ key, state: { status: 'ok', data } }),
      (err: unknown) => {
        if (!live) return
        const message = err instanceof Error ? err.message : String(err)
        const state: CriticalLinksState =
          err instanceof ApiError && err.status === 501
            ? { status: 'unavailable', message }
            : { status: 'error', message }
        setResult({ key, state })
      },
    )
    return () => {
      live = false
    }
  }, [key, timestep, horizon])

  return result && result.key === key ? result.state : { status: 'loading' }
}

/** A link's identity across timesteps: its ways. */
export const linkKey = (way_ids: number[]): string => way_ids.join('-')
