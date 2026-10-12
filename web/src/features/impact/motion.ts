// When the isolated-facility halo may move. It pulses only while there is something to see
// (isolated facilities in the map's view, page visible), as one breath followed by a rest, so the
// map is idle most of the time; under prefers-reduced-motion it is a static halo.
import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

function subscribeReducedMotion(onChange: () => void) {
  const query = window.matchMedia(REDUCED_MOTION)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

/** prefers-reduced-motion: reduce, kept up to date. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReducedMotion, () => window.matchMedia(REDUCED_MOTION).matches)
}

function subscribeVisibility(onChange: () => void) {
  document.addEventListener('visibilitychange', onChange)
  return () => document.removeEventListener('visibilitychange', onChange)
}

/** The page is visible (not a background tab or minimised window). */
export function usePageVisible(): boolean {
  return useSyncExternalStore(subscribeVisibility, () => document.visibilityState === 'visible')
}

/** Whether any point is inside the map's current view; re-checked when the map stops moving. */
export function useAnyInView(map: MapLibreMap | null, points: [number, number][]): boolean {
  // The view as a string snapshot (stable between moves), so React re-renders only on change.
  const subscribe = useCallback(
    (onChange: () => void) => {
      map?.on('moveend', onChange)
      return () => void map?.off('moveend', onChange)
    },
    [map],
  )
  const snapshot = useCallback(() => (map ? map.getBounds().toArray().flat().join(',') : ''), [map])
  const view = useSyncExternalStore(subscribe, snapshot)
  return useMemo(() => {
    if (!view) return points.length > 0 // no map yet: assume visible
    const [west, south, east, north] = view.split(',').map(Number)
    return points.some(([lon, lat]) => lon >= west && lon <= east && lat >= south && lat <= north)
  }, [view, points])
}

/**
 * While `active`: true for `periodMs` (the halo grows), false for `periodMs` (it shrinks back),
 * then a `restMs` pause with nothing animating. Inactive: false, and no timers at all.
 */
export function usePulse(active: boolean, periodMs: number, restMs: number): boolean {
  const [on, setOn] = useState(false)
  useEffect(() => {
    if (!active) return
    let id = 0
    const shrink = () => {
      setOn(false)
      id = window.setTimeout(grow, periodMs + restMs)
    }
    const grow = () => {
      setOn(true)
      id = window.setTimeout(shrink, periodMs)
    }
    id = window.setTimeout(grow, restMs)
    return () => window.clearTimeout(id)
  }, [active, periodMs, restMs])
  return active && on
}
