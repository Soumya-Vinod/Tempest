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

// --- Expected hazard, next 24 h (v1.3): composited here from the per-timestep layers ------------

const FORECAST_STEPS = 24 / 3
const expectedCache = new Map<string, Promise<HazardLayer[]>>()

const cellKey = (f: HazardLayer) => f.properties.id.split('__')[1] ?? f.properties.id

/**
 * The cell-wise max of a hazard over the timestep and the next 24 h (capped at landfall), as the
 * API's horizon 24 does for impact and risk: a perfect-forecast replay. Labelled with the
 * timestep's own cells. Cached per (type, timestep), so images and contours built from it are
 * reused while scrubbing.
 */
function loadExpected(type: HazardType, timestepIndex: number): Promise<HazardLayer[]> {
  const key = `${type}|${REPLAY_TIMESTEPS[timestepIndex]}`
  const hit = expectedCache.get(key)
  if (hit) return hit
  const window = REPLAY_TIMESTEPS.slice(timestepIndex, timestepIndex + FORECAST_STEPS + 1)
  const promise = Promise.all(window.map((ts) => load(type, ts))).then((layers) => {
    const best = new Map<string, number>()
    for (const layer of layers)
      for (const f of layer)
        best.set(cellKey(f), Math.max(best.get(cellKey(f)) ?? -Infinity, f.properties.value))
    return layers[0].map((f) => ({
      ...f,
      properties: { ...f.properties, value: best.get(cellKey(f)) ?? f.properties.value },
    }))
  })
  promise.catch(() => expectedCache.delete(key))
  expectedCache.set(key, promise)
  while (expectedCache.size > CACHE_SIZE) expectedCache.delete(expectedCache.keys().next().value!)
  return promise
}

/** useHazardLayer for the expected hazard over the next 24 h. */
export function useExpectedLayer(
  type: HazardType,
  timestepIndex: number,
  enabled: boolean,
): { state: HazardState<HazardLayer[]>; shown: HazardLayer[] } {
  const key = `${type}|expected|${REPLAY_TIMESTEPS[timestepIndex]}`
  const [settled, setSettled] = useState<Settled | null>(null)
  const [lastOk, setLastOk] = useState<HazardLayer[]>([])
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    loadExpected(type, timestepIndex).then(
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
  }, [enabled, key, type, timestepIndex])
  if (!enabled) return { state: { status: 'off' }, shown: [] }
  const state: HazardState<HazardLayer[]> =
    settled?.key === key ? settled.state : { status: 'loading' }
  return { state, shown: state.status === 'ok' ? state.data : lastOk }
}
