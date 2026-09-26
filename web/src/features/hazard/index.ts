// Hazard feature (Dev B, reassigned from Dev A): the Hazard / Risk map-view switch, surge, wind
// and flood cells, the storm track, the Storm panel section and the out-of-view storm arrow.
// Frontend only, on Dev A's /api/hazard/layers and /api/hazard/track routes.
import type { Layer } from '@deck.gl/core'
import type { LngLatBoundsLike, Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useMemo, useState } from 'react'

import { LANDFALL_INDEX, REPLAY_TIMESTEPS } from '../../lib/constants'
import { fitAoi, fitPadded } from '../../lib/mapFit'
import type { CycloneTrackPoint, Horizon } from '../../types/contracts'
import type { HazardPanelProps } from './HazardPanel'
import { buildHazardFills, buildTrackLayers, hazardTooltip } from './layers'
import { imdCategory, toKmh } from './style'
import { type MapViewMode, useExpectedLayer, useHazardLayer, useTrack } from './useHazard'

export { default as HazardPanel } from './HazardPanel'
export { default as StormEdge } from './StormEdge'

export type { MapViewMode } from './useHazard'

export interface HazardMap {
  /** Area fills (drawn in the fills slot, below exposure), empty in the Risk view. */
  fillLayers: Layer[]
  /** The storm track (both views), above impact. */
  trackLayers: Layer[]
  tooltip: typeof hazardTooltip
  panel: HazardPanelProps
  edge: { map: MapLibreMap | null; storm: [number, number] | null; category: string }
}

const TRACK_MARGIN_DEG = 0.5

/** Hazard layers for the scrubber's timestep, in the given view. */
export function useHazardMap(
  timestepIndex: number,
  view: MapViewMode,
  onView: (view: MapViewMode) => void,
  map: MapLibreMap | null,
  horizon: Horizon = 0,
  onHorizon: (horizon: Horizon) => void = () => {},
): HazardMap {
  const timestep = REPLAY_TIMESTEPS[timestepIndex]
  const hazardView = view === 'hazard'
  const [windOn, setWindOn] = useState(false)
  const [floodOn, setFloodOn] = useState(false)
  const [fullTrack, setFullTrack] = useState(false)

  // Now: the observed layers. Next 24 h (v1.3): the cell-wise max over the next 24 h, composited
  // from the same cached layers (useExpectedLayer), so it matches impact and risk at horizon 24.
  const expected = horizon === 24
  const surgeNow = useHazardLayer('surge', timestep, hazardView && !expected)
  const windNow = useHazardLayer('wind', timestep, hazardView && windOn && !expected)
  const surgeNext = useExpectedLayer('surge', timestepIndex, hazardView && expected)
  const windNext = useExpectedLayer('wind', timestepIndex, hazardView && windOn && expected)
  const surge = expected ? surgeNext : surgeNow
  const wind = expected ? windNext : windNow
  const flood = useHazardLayer('flood', timestep, hazardView && floodOn)
  const track = useTrack()
  const points: CycloneTrackPoint[] = useMemo(
    () => (track.status === 'ok' ? track.data.points : []),
    [track],
  )
  // The track has a point per replay timestep; match by timestep rather than by position.
  const trackIndex = points.findIndex((p) => p.timestep === timestep)
  const point = trackIndex >= 0 ? points[trackIndex] : null

  const fillLayers = useMemo(
    () =>
      buildHazardFills({
        flood: hazardView && floodOn ? flood.shown : null,
        surge: hazardView ? surge.shown : null,
        wind: hazardView && windOn ? wind.shown : null,
      }),
    [hazardView, floodOn, windOn, flood.shown, surge.shown, wind.shown],
  )
  const trackLayers = useMemo(() => buildTrackLayers(points, trackIndex), [points, trackIndex])

  const onFullTrack = useCallback(() => {
    if (!map || points.length === 0) return
    const lons = points.map((p) => p.lon)
    const lats = points.map((p) => p.lat)
    const bounds: LngLatBoundsLike = [
      [Math.min(...lons) - TRACK_MARGIN_DEG, Math.min(...lats) - TRACK_MARGIN_DEG],
      [Math.max(...lons) + TRACK_MARGIN_DEG, Math.max(...lats) + TRACK_MARGIN_DEG],
    ]
    fitPadded(map, bounds, true)
    setFullTrack(true)
  }, [map, points])
  const onBackToAoi = useCallback(() => {
    if (map) fitAoi(map, true)
    setFullTrack(false)
  }, [map])

  const storm = useMemo<[number, number] | null>(
    () => (point ? [point.lon, point.lat] : null),
    [point],
  )
  const category = point
    ? (imdCategory(toKmh(point.max_wind_mps))?.name ?? 'Below depression strength')
    : ''

  return {
    fillLayers,
    trackLayers,
    tooltip: hazardTooltip,
    panel: {
      view,
      onView,
      horizon,
      onHorizon,
      surge: surge.state,
      wind: { on: windOn, onToggle: () => setWindOn((v) => !v), state: wind.state },
      flood: { on: floodOn, onToggle: () => setFloodOn((v) => !v), state: flood.state },
      storm: {
        state: track,
        point,
        hoursToLandfall: (LANDFALL_INDEX - timestepIndex) * 3,
        fullTrack,
        onFullTrack,
        onBackToAoi,
      },
    },
    edge: { map, storm, category },
  }
}
