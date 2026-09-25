import { useEffect, useState } from 'react'

import { ApiError, getRiskBreakdown, getRiskScores, getUnscoredAreas } from '../../lib/api'
import type {
  RiskBreakdown,
  RiskScoreCollection,
  Timestep,
  UnscoredAreaCollection,
} from '../../types/contracts'

export interface RiskData {
  scores: RiskScoreCollection
  breakdown: RiskBreakdown | null // explains the card; the map works without it
}

export type RiskState =
  | { status: 'loading' }
  | { status: 'ok'; data: RiskData }
  | { status: 'unavailable'; message: string } // 501: no hazard data (or demo fixture) yet
  | { status: 'error'; message: string }

// Recently used timesteps, most recent last. Only successful loads stay cached.
const CACHE_SIZE = 8
const cache = new Map<string, Promise<RiskData>>()

function load(timestep: Timestep, synthetic: boolean): Promise<RiskData> {
  const key = `${timestep}|${synthetic}`
  const hit = cache.get(key)
  if (hit) {
    cache.delete(key)
    cache.set(key, hit)
    return hit
  }
  const promise = Promise.all([
    getRiskScores(timestep, { synthetic }),
    getRiskBreakdown(timestep, { synthetic }).catch(() => null),
  ]).then(([scores, breakdown]) => ({ scores, breakdown }))
  promise.catch(() => cache.delete(key))
  cache.set(key, promise)
  while (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value!)
  return promise
}

function failure(err: unknown): RiskState {
  const message = err instanceof Error ? err.message : String(err)
  return err instanceof ApiError && err.status === 501
    ? { status: 'unavailable', message }
    : { status: 'error', message }
}

/**
 * Risk scores (and breakdown) for the selected timestep. `shown` keeps the last successful data
 * on the map while the next timestep loads, as impact does.
 */
export function useRisk(
  timestep: Timestep,
  synthetic: boolean,
): { state: RiskState; shown: RiskData | null } {
  const key = `${timestep}|${synthetic}`
  const [settled, setSettled] = useState<{ key: string; state: RiskState } | null>(null)
  const [lastOk, setLastOk] = useState<RiskData | null>(null)

  useEffect(() => {
    let cancelled = false
    load(timestep, synthetic).then(
      (data) => {
        if (cancelled) return
        setSettled({ key, state: { status: 'ok', data } })
        setLastOk(data)
      },
      (err: unknown) => {
        if (cancelled) return
        setSettled({ key, state: failure(err) })
        setLastOk(null)
      },
    )
    return () => {
      cancelled = true
    }
  }, [key, timestep, synthetic])

  const state: RiskState = settled?.key === key ? settled.state : { status: 'loading' }
  return { state, shown: state.status === 'ok' ? state.data : lastOk }
}

/** Kolkata and municipal areas outside the blocks (static; loaded once). */
export function useUnscoredAreas(): UnscoredAreaCollection | null {
  const [data, setData] = useState<UnscoredAreaCollection | null>(null)
  useEffect(() => {
    let cancelled = false
    getUnscoredAreas().then(
      (fc) => {
        if (!cancelled) setData(fc)
      },
      () => {}, // no reference data (503): simply no hatched layer
    )
    return () => {
      cancelled = true
    }
  }, [])
  return data
}
