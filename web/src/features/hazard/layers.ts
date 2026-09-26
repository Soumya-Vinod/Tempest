// deck.gl layers for the hazard view (flood, surge, wind cells) and the storm track (both views).
import type { Layer, PickingInfo } from '@deck.gl/core'
import { PathStyleExtension, type PathStyleExtensionProps } from '@deck.gl/extensions'
import { GeoJsonLayer, PathLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers'

import type { CycloneTrackPoint, HazardLayer } from '../../types/contracts'
import {
  floodColor,
  imdCategory,
  STORM_FILL,
  STORM_OUTLINE,
  SURGE_MIN_M,
  surgeColor,
  toKmh,
  TRACK_COLOR,
  TRACK_FUTURE_COLOR,
  windColor,
} from './style'

const EMPTY = { type: 'FeatureCollection' as const, features: [] as HazardLayer[] }
const collection = (features: HazardLayer[]) => ({ ...EMPTY, features })

/** Area fills, bottom to top: flood susceptibility, surge, wind. */
export function buildHazardFills(cells: {
  flood: HazardLayer[] | null
  surge: HazardLayer[] | null
  wind: HazardLayer[] | null
}): Layer[] {
  const surge = (cells.surge ?? []).filter((f) => f.properties.value > SURGE_MIN_M)
  const wind = (cells.wind ?? []).filter((f) => imdCategory(toKmh(f.properties.value)))
  return [
    new GeoJsonLayer<HazardLayer['properties']>({
      id: 'hazard-flood',
      data: collection(cells.flood ?? []),
      visible: cells.flood !== null,
      pickable: true,
      stroked: false,
      getFillColor: (f) => floodColor(f.properties.severity),
    }),
    new GeoJsonLayer<HazardLayer['properties']>({
      id: 'hazard-surge',
      data: collection(surge),
      visible: cells.surge !== null,
      pickable: true,
      stroked: false,
      getFillColor: (f) => surgeColor(f.properties.value),
    }),
    new GeoJsonLayer<HazardLayer['properties']>({
      id: 'hazard-wind',
      data: collection(wind),
      visible: cells.wind !== null,
      pickable: true,
      stroked: false,
      getFillColor: (f) => windColor(f.properties.value),
    }),
  ]
}

const lonLat = (p: CycloneTrackPoint): [number, number] => [p.lon, p.lat]

/**
 * The track: solid up to the scrubber's timestep, dashed after it; the storm's position with its
 * IMD category as a label.
 */
export function buildTrackLayers(points: CycloneTrackPoint[], index: number): Layer[] {
  if (points.length === 0 || index < 0) return []
  const i = Math.min(index, points.length - 1)
  const current = points[i]
  const category = imdCategory(toKmh(current.max_wind_mps))
  return [
    new PathLayer<CycloneTrackPoint[]>({
      id: 'track-past',
      data: [points.slice(0, i + 1)],
      getPath: (d) => d.map(lonLat),
      getColor: TRACK_COLOR,
      widthUnits: 'pixels',
      getWidth: 3,
      capRounded: true,
      jointRounded: true,
    }),
    new PathLayer<CycloneTrackPoint[], PathStyleExtensionProps<CycloneTrackPoint[]>>({
      id: 'track-future',
      data: i < points.length - 1 ? [points.slice(i)] : [],
      getPath: (d) => d.map(lonLat),
      getColor: TRACK_FUTURE_COLOR,
      widthUnits: 'pixels',
      getWidth: 2,
      getDashArray: [6, 5],
      dashJustified: true,
      extensions: [new PathStyleExtension({ dash: true })],
    }),
    new ScatterplotLayer<CycloneTrackPoint>({
      id: 'track-storm',
      data: [current],
      pickable: true,
      getPosition: lonLat,
      radiusUnits: 'pixels',
      getRadius: 8,
      getFillColor: STORM_FILL,
      stroked: true,
      getLineColor: STORM_OUTLINE,
      lineWidthUnits: 'pixels',
      getLineWidth: 2,
    }),
    new TextLayer<CycloneTrackPoint>({
      id: 'track-label',
      data: [current],
      getPosition: lonLat,
      getText: () => category?.name ?? 'Below depression strength',
      getSize: 12,
      getColor: [15, 23, 42, 255],
      getPixelOffset: [12, 0],
      getTextAnchor: 'start',
      getAlignmentBaseline: 'center',
      background: true,
      getBackgroundColor: [255, 255, 255, 220],
      backgroundPadding: [4, 2],
      fontWeight: 600,
    }),
  ]
}

const TOOLTIP_STYLE: Partial<CSSStyleDeclaration> = {
  backgroundColor: 'white',
  color: '#1e293b',
  fontSize: '12px',
  lineHeight: '1.4',
  padding: '6px 8px',
  borderRadius: '6px',
  boxShadow: '0 2px 8px rgb(0 0 0 / 0.2)',
  maxWidth: '260px',
}

/** Hover card for a hazard cell or the storm (same look as the other tooltips), or null. */
export function hazardTooltip(info: PickingInfo): { text: string; style: Partial<CSSStyleDeclaration> } | null {
  const text = hazardText(info)
  return text ? { text, style: TOOLTIP_STYLE } : null
}

function hazardText(info: PickingInfo): string | null {
  const id = info.layer?.id
  if (!info.object || !id) return null
  if (id === 'track-storm') {
    const p = info.object as CycloneTrackPoint
    const kmh = toKmh(p.max_wind_mps)
    const category = imdCategory(kmh)
    return `Cyclone Amphan\n${Math.round(kmh)} km/h${category ? `, ${category.name}` : ''}\n${p.central_pressure_hpa} hPa`
  }
  if (!id.startsWith('hazard-')) return null
  const p = (info.object as HazardLayer).properties
  if (id === 'hazard-surge') return `Storm surge ${p.value.toFixed(1)} m above ground`
  if (id === 'hazard-wind') {
    const kmh = toKmh(p.value)
    return `Wind ${Math.round(kmh)} km/h, ${imdCategory(kmh)?.name ?? 'below depression'}`
  }
  return `Flood susceptibility ${p.severity.toFixed(2)} (static)`
}
