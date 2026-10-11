// Prefetch the timesteps around the scrubber's (±1, ±2) in the API's low-priority lane, so
// stepping and Play find their data already loaded. Nearest first, in the direction of travel;
// a step change drops queued prefetches that are no longer wanted (e.g. after reversing).
import { useEffect, useRef } from 'react'

import { NON_OK } from '../features/impact/style'
import type { Horizon, Timestep } from '../types/contracts'
import { cancelPrefetches, prefetch, type Query, requestKey } from './api'

const GROUP = 'around'

/** The GETs the panels and map make for one timestep (same paths and queries as lib/api.ts). */
function plan(timestep: Timestep, horizon: Horizon, hazardView: boolean): [string, Query][] {
  const h = String(horizon)
  const out: [string, Query][] = []
  for (const hz of horizon === 0 ? ['0'] : [h, '0']) {
    for (const status of NON_OK) out.push(['/api/impact/results', { timestep, status, horizon: hz }])
  }
  out.push(['/api/impact/countdown', { timestep }])
  out.push(['/api/impact/critical-links', { timestep, horizon: h }])
  out.push(['/api/risk/scores', { timestep, horizon: h }])
  out.push(['/api/risk/breakdown', { timestep, horizon: h }])
  out.push(['/api/insurance/triggers', { timestep }])
  if (hazardView && horizon === 0) out.push(['/api/hazard/layers', { hazard_type: 'surge', timestep }])
  return out
}

export function usePrefetchAround(
  index: number,
  timesteps: readonly Timestep[],
  horizon: Horizon,
  hazardView: boolean,
): void {
  const last = useRef(index)
  const direction = useRef(1)
  useEffect(() => {
    if (index !== last.current) direction.current = index > last.current ? 1 : -1
    last.current = index
    const offsets = direction.current > 0 ? [1, 2, -1, -2] : [-1, -2, 1, 2]
    const requests = offsets
      .map((d) => timesteps[index + d])
      .filter((ts): ts is Timestep => ts !== undefined)
      .flatMap((ts) => plan(ts, horizon, hazardView))
    const wanted = new Set(requests.map(([path, query]) => requestKey(path, query)))
    cancelPrefetches(GROUP, (key) => wanted.has(key))
    for (const [path, query] of requests) prefetch(GROUP, path, query)
  }, [index, timesteps, horizon, hazardView])
}
