import { useEffect, useState } from 'react'

import { ApiError, getHazardLayer, getHazardTrack } from '../../lib/api'
import { REPLAY_TIMESTEPS } from '../../lib/constants'
import type { CycloneTrack, HazardLayer, HazardType, Timestep } from '../../types/contracts'

/** Hazard: surge (+ wind / flood) cells. Risk: the block choropleth. Never both (both are fills). */
export type MapViewMode = 'hazard' | 'risk'

export type HazardState<T> =
  | { status: 'off' } // layer not shown: nothing fetched
  | { status: 'loading' }
  | { status: 'ok'; data: T }
  | { status: 'unavailable'; message: string } // 501 / 503 (or 404: route not there yet)
  | { status: 'error'; message: string }

// Recently used (hazard type, timestep) pairs, most recent last. Only successful loads stay.
const CACHE_SIZE = 8 * 3
const cache = new Map<string, Promise<HazardLayer[]>>()

/** Flood susceptibility is static (the same at every timestep): one request serves them all. */
const FLOOD_TIMESTEP = REPLAY_TIMESTEPS[0]

function load(type: HazardType, timestep: Timestep): Promise<HazardLayer[]> {
  const key = type === 'flood' ? 'flood' : `${type}|${timestep}`
  const hit = cache.get(key)
  if (hit) {
    cache.delete(key)
    cache.set(key, hit)
    return hit
  }
  const promise = getHazardLayer(type, type === 'flood' ? FLOOD_TIMESTEP : timestep).then(
    (fc) => fc.features,
  )
  promise.catch(() => cache.delete(key))
  cache.set(key, promise)
  while (cache.size > CACHE_SIZE) cache.delete(cache.keys().next().value!)
  return promise
}

function failure<T>(err: unknown): HazardState<T> {
  const message = err instanceof Error ? err.message : String(err)
  return err instanceof ApiError && [404, 501, 503].includes(err.status)
    ? { status: 'unavailable', message }
    : { status: 'error', message }
}

interface Settled {
  key: string
  state: HazardState<HazardLayer[]>
}

/**
 * One hazard layer for the timestep, fetched only while `enabled`. `shown` keeps the last
 * successful cells on the map while the next timestep loads, so scrubbing doesn't flicker.
 */
export function useHazardLayer(
  type: HazardType,
  timestep: Timestep,
  enabled: boolean,
): { state: HazardState<HazardLayer[]>; shown: HazardLayer[] } {
  const key = `${type}|${type === 'flood' ? 'static' : timestep}`
  const [settled, setSettled] = useState<Settled | null>(null)
  const [lastOk, setLastOk] = useState<HazardLayer[]>([])

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    load(type, timestep).then(
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
  }, [enabled, key, type, timestep])

  if (!enabled) return { state: { status: 'off' }, shown: [] }
  const state: HazardState<HazardLayer[]> =
    settled?.key === key ? settled.state : { status: 'loading' }
  return { state, shown: state.status === 'ok' ? state.data : lastOk }
}

let trackPromise: Promise<CycloneTrack> | null = null

/** The replay track, fetched once per page load (a failed load is retried on the next mount). */
export function useTrack(): HazardState<CycloneTrack> {
  const [state, setState] = useState<HazardState<CycloneTrack>>({ status: 'loading' })
  useEffect(() => {
    let cancelled = false
    trackPromise ??= getHazardTrack()
    trackPromise.then(
      (data) => !cancelled && setState({ status: 'ok', data }),
      (err: unknown) => {
        trackPromise = null
        if (!cancelled) setState(failure(err))
      },
    )
    return () => {
      cancelled = true
    }
  }, [])
  return state
}
