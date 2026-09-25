import { useEffect, useState } from 'react'

import { ApiError, getHealth, getImpactResults } from '../../lib/api'
import type { ImpactResult, Timestep } from '../../types/contracts'
import { NON_OK } from './style'

export type ImpactState =
  | { status: 'loading' }
  | { status: 'ok'; data: ImpactResult[] }
  | { status: 'unavailable'; message: string } // 501: no hazard data (or demo fixture) yet
  | { status: 'error'; message: string }

// Recently used timesteps, most recent last. Only successful loads stay cached.
const CACHE_SIZE = 8
const cache = new Map<string, Promise<ImpactResult[]>>()

/**
 * Non-ok rows for one timestep. The contract's `status` filter takes one value, so this makes
 * one request per non-ok status and merges them; ok rows are never downloaded.
 */
function load(timestep: Timestep, synthetic: boolean): Promise<ImpactResult[]> {
  const key = `${timestep}|${synthetic}`
  const hit = cache.get(key)
  if (hit) {
    cache.delete(key)
    cache.set(key, hit)
    return hit
  }
  const promise = Promise.all(
    NON_OK.map((status) => getImpactResults(timestep, { status }, { synthetic })),
  ).then((parts) => parts.flatMap((fc) => fc.features))
  promise.catch(() => cache.delete(key))
  cache.set(key, promise)
  while (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value!)
  return promise
}

function failure(err: unknown): ImpactState {
  const message = err instanceof Error ? err.message : String(err)
  return err instanceof ApiError && err.status === 501
    ? { status: 'unavailable', message }
    : { status: 'error', message }
}

interface Settled {
  key: string
  state: ImpactState
}

/**
 * Impact results for the selected timestep. `state` is for the current key; `shown` keeps the
 * last successful data on the map while the next timestep loads, so scrubbing doesn't flicker.
 */
export function useImpacts(
  timestep: Timestep,
  synthetic: boolean,
): { state: ImpactState; shown: ImpactResult[] } {
  const key = `${timestep}|${synthetic}`
  const [settled, setSettled] = useState<Settled | null>(null)
  const [lastOk, setLastOk] = useState<ImpactResult[]>([])

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
        setLastOk([])
      },
    )
    return () => {
      cancelled = true
    }
  }, [key, timestep, synthetic])

  const state: ImpactState = settled?.key === key ? settled.state : { status: 'loading' }
  return { state, shown: state.status === 'ok' ? state.data : lastOk }
}

/** DEMO_MODE from /health: null until known (the synthetic toggle stays hidden meanwhile). */
export function useDemoMode(): boolean | null {
  const [demoMode, setDemoMode] = useState<boolean | null>(null)
  useEffect(() => {
    let cancelled = false
    getHealth().then(
      (h) => {
        if (!cancelled) setDemoMode(h.demo_mode)
      },
      () => {}, // unreachable backend: HealthPanel already reports it
    )
    return () => {
      cancelled = true
    }
  }, [])
  return demoMode
}

/** Flips every PULSE_MS while active; the ring layer animates between the two sizes. */
export function usePulse(active: boolean, periodMs: number): boolean {
  const [on, setOn] = useState(false)
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setOn((v) => !v), periodMs)
    return () => clearInterval(id)
  }, [active, periodMs])
  return active && on
}
