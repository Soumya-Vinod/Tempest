import { useEffect, useState } from 'react'

import { ApiError, getInsuranceSummary, getTriggers } from '../../lib/api'
import type {
  InsuranceSummary,
  Timestep,
  TriggerEvent,
} from '../../types/contracts'

export type Loadable<T> =
  | { status: 'loading' }
  | { status: 'ok'; data: T }
  | { status: 'unavailable'; message: string } // 501 / 503: no hazard data or fixture yet
  | { status: 'error'; message: string }

function failure<T>(err: unknown): Loadable<T> {
  const message = err instanceof Error ? err.message : String(err)
  return err instanceof ApiError && [501, 503].includes(err.status)
    ? { status: 'unavailable', message }
    : { status: 'error', message }
}

// Recently used timesteps, most recent last. Only successful loads stay cached.
const CACHE_SIZE = 8
const cache = new Map<string, Promise<TriggerEvent[]>>()

function load(timestep: Timestep): Promise<TriggerEvent[]> {
  const hit = cache.get(timestep)
  if (hit) {
    cache.delete(timestep)
    cache.set(timestep, hit)
    return hit
  }
  const promise = getTriggers(timestep).then((fc) => fc.features)
  promise.catch(() => cache.delete(timestep))
  cache.set(timestep, promise)
  while (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value!)
  return promise
}

/** One TriggerEvent per block for the timestep; `shown` keeps the last ones while loading. */
export function useTriggers(timestep: Timestep): {
  state: Loadable<TriggerEvent[]>
  shown: TriggerEvent[]
} {
  const [settled, setSettled] = useState<{ key: Timestep; state: Loadable<TriggerEvent[]> }>()
  const [lastOk, setLastOk] = useState<TriggerEvent[]>([])
  useEffect(() => {
    let cancelled = false
    load(timestep).then(
      (data) => {
        if (cancelled) return
        setSettled({ key: timestep, state: { status: 'ok', data } })
        setLastOk(data)
      },
      (err: unknown) => !cancelled && setSettled({ key: timestep, state: failure(err) }),
    )
    return () => {
      cancelled = true
    }
  }, [timestep])
  const state: Loadable<TriggerEvent[]> =
    settled?.key === timestep ? settled.state : { status: 'loading' }
  return { state, shown: state.status === 'ok' ? state.data : lastOk }
}

let summaryPromise: Promise<InsuranceSummary> | null = null

/** First triggers and released totals for all 25 timesteps, fetched once. */
export function useInsuranceSummary(): Loadable<InsuranceSummary> {
  const [state, setState] = useState<Loadable<InsuranceSummary>>({ status: 'loading' })
  useEffect(() => {
    let cancelled = false
    summaryPromise ??= getInsuranceSummary()
    summaryPromise.then(
      (data) => !cancelled && setState({ status: 'ok', data }),
      (err: unknown) => {
        summaryPromise = null
        if (!cancelled) setState(failure(err))
      },
    )
    return () => {
      cancelled = true
    }
  }, [])
  return state
}
