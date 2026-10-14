// deck.gl layers for the hazard view (flood, surge, wind cells) and the storm track (both views).
import type { Color, Layer, PickingInfo } from '@deck.gl/core'
import type { MaskExtensionProps, PathStyleExtensionProps } from '@deck.gl/extensions'
import type { BitmapLayerProps } from '@deck.gl/layers'
import type { Feature } from 'geojson'

import type { Deck } from '../../lib/deck'
import type { CycloneTrackPoint, HazardLayer } from '../../types/contracts'
import { type Isotach, type IsotachLabel, isotachs } from './contours'
import land from './land.json'
import { type Colorize, hazardImage } from './raster'
import {
  floodColor,
  imdCategory,
  ISOTACH_COLOR,
  ISOTACH_LABEL_BG,
  isotachWidth,
  STORM_FILL,
  STORM_HALO,
  STORM_OUTLINE,
  SURGE_MIN_M,
  surgePixel,
  toKmh,
  TRACK_CASING,
  TRACK_CASING_PX,
  TRACK_COLOR,
  TRACK_FUTURE_COLOR,
  TRACK_NEXT_COLOR,
  TRACK_NEXT_H,
  TRACK_WIDTH,
} from './style'

const EMPTY = { type: 'FeatureCollection' as const, features: [] as HazardLayer[] }
const collection = (features: HazardLayer[]) => ({ ...EMPTY, features })

// Land mask: South 24 Parganas + Kolkata land (unfilled OSM districts), bundled simplified.
// Generated from api/data/reference/s24p_land.geojson (351 KB): union, simplify 100 m in UTM 45N
// (EPSG:32645, topology kept), round to 1e-4°, GeoJSON Feature, 52 KB, 90 parts, area within
// 0.04 %. Nothing is drawn or pickable outside it: not over the sea, rivers, N 24 Parganas or
// Bangladesh.
const LAND_MASK_ID = 'hazard-land-mask'
const mask = (deck: Deck) => ({ extensions: [new deck.MaskExtension()], maskId: LAND_MASK_ID })
const LINEAR: BitmapLayerProps['textureParameters'] = {
  minFilter: 'linear',
  magFilter: 'linear',
}
// Nearly transparent: deck.gl picks it, the eye doesn't see it.
const PICK_ONLY: Color = [0, 0, 0, 1]

function landMask(deck: Deck): Layer {
  return new deck.GeoJsonLayer({ id: LAND_MASK_ID, data: land as Feature, operation: 'mask' })
}

/** A smoothed, land-masked image of one hazard (null data: hidden). */
function imageLayer(
  deck: Deck,
  id: string,
  cells: HazardLayer[] | null,
  colorize: Colorize,
): Layer[] {
  const img = cells ? hazardImage(cells, colorize) : null
  if (!img) return []
  return [
    new deck.BitmapLayer({
      id,
      image: img.image,
      bounds: img.bounds,
      textureParameters: LINEAR,
      pickable: false,
      ...mask(deck),
    }),
  ]
}

/** One hover target per grid cell, with every hazard shown there (one tooltip for all). */
interface CellValues {
  geometry: HazardLayer['geometry']
  surge: number | null
  wind: number | null
  flood: number | null
}

/** "c0042" from "surge__c0042__20200520T0900Z": the same cell across hazard types. */
const cellKey = (f: HazardLayer) => f.properties.id.split('__')[1] ?? f.properties.id

function cellValues(cells: {
  flood: HazardLayer[] | null
  surge: HazardLayer[] | null
  wind: HazardLayer[] | null
}): CellValues[] {
  const out = new Map<string, CellValues>()
  const add = (layer: HazardLayer[] | null, set: (v: CellValues, f: HazardLayer) => void) => {
    for (const f of layer ?? []) {
      const key = cellKey(f)
      let v = out.get(key)
      if (!v) out.set(key, (v = { geometry: f.geometry, surge: null, wind: null, flood: null }))
      set(v, f)
    }
  }
  add(cells.surge, (v, f) => (v.surge = f.properties.value))
  add(cells.wind, (v, f) => (v.wind = f.properties.value))
  add(cells.flood, (v, f) => (v.flood = f.properties.severity))
  return [...out.values()]
}

/**
 * Hazard fills, bottom to top: flood susceptibility (masked cells), surge (smoothed, masked
 * image), wind isotachs (masked lines with km/h labels), then one invisible, masked hover layer
 * per cell for the tooltip. Everything is clipped to land by the mask layer.
 */
export function buildHazardFills(
  deck: Deck,
  cells: {
    flood: HazardLayer[] | null
    surge: HazardLayer[] | null
    wind: HazardLayer[] | null
  },
): Layer[] {
  const { GeoJsonLayer, MaskExtension, PathLayer, PolygonLayer, TextLayer } = deck
  const MASK = mask(deck)
  const layers: Layer[] = [landMask(deck)]
  if (cells.flood) {
    layers.push(
      new GeoJsonLayer<HazardLayer['properties']>({
        id: 'hazard-flood',
        data: collection(cells.flood),
        pickable: false, // hovered through hazard-cells
        stroked: false,
        getFillColor: (f) => floodColor(f.properties.severity),
        ...MASK,
      }),
    )
  }
  if (cells.surge) layers.push(...imageLayer(deck, 'hazard-surge-image', cells.surge, surgePixel))
  if (cells.flood || cells.surge || cells.wind) {
    layers.push(
      new PolygonLayer<CellValues>({
        id: 'hazard-cells',
        data: cellValues(cells),
        getPolygon: (d) => (d.geometry.type === 'Polygon' ? d.geometry.coordinates : d.geometry.coordinates[0]),
        pickable: true,
        stroked: false,
        getFillColor: PICK_ONLY,
        ...MASK,
      }),
    )
  }
  if (cells.wind) {
    const { lines, labels } = isotachs(cells.wind)
    layers.push(
      new PathLayer<Isotach>({
        id: 'hazard-isotachs',
        data: lines,
        getPath: (d) => d.path,
        getColor: ISOTACH_COLOR,
        widthUnits: 'pixels',
        getWidth: (d) => isotachWidth(d.level),
        jointRounded: true,
        capRounded: true,
        pickable: true,
        ...MASK,
      }),
      new TextLayer<IsotachLabel, MaskExtensionProps>({
        id: 'hazard-isotach-labels',
        data: labels,
        getPosition: (d) => d.position,
        getText: (d) => `${d.kmh} km/h`,
        getSize: 11,
        getColor: ISOTACH_COLOR,
        fontWeight: 500,
        background: true,
        getBackgroundColor: ISOTACH_LABEL_BG,
        backgroundPadding: [3, 1],
        extensions: [new MaskExtension()],
        maskId: LAND_MASK_ID,
        maskByInstance: true, // whole labels, by anchor
      }),
    )
  }
  return layers
}

const lonLat = (p: CycloneTrackPoint): [number, number] => [p.lon, p.lat]

/**
 * The track: solid up to the scrubber's timestep, dashed after it, and the storm's position. No
 * label on the map (it would cover the coast): the category is in the tooltip, the timeline and
 * the Situation tab.
 */
export function buildTrackLayers(deck: Deck, points: CycloneTrackPoint[], index: number): Layer[] {
  if (points.length === 0 || index < 0) return []
  const { PathLayer, PathStyleExtension, ScatterplotLayer } = deck
  const i = Math.min(index, points.length - 1)
  const current = points[i]
  // The next 24 h of track (by time, so it doesn't depend on the step length), then the rest.
  const horizonMs = Date.parse(current.timestep) + TRACK_NEXT_H * 3600 * 1000
  let next = i
  while (next + 1 < points.length && Date.parse(points[next + 1].timestep) <= horizonMs) next++
  const past = [points.slice(0, i + 1)]
  const later = next < points.length - 1 ? [points.slice(next)] : []
  const soon = next > i ? [points.slice(i, next + 1)] : []
  // A white casing under every segment, so the track stays apart from the slate roads where its
  // pink reads as grey (deuteranopia). Solid under the dashed part too: dashes on a white band.
  const casing = (id: string, data: CycloneTrackPoint[][], width: number) =>
    new PathLayer<CycloneTrackPoint[]>({
      id: `${id}-casing`,
      data,
      getPath: (d) => d.map(lonLat),
      getColor: TRACK_CASING,
      widthUnits: 'pixels',
      getWidth: width + 2 * TRACK_CASING_PX,
      capRounded: true,
      jointRounded: true,
    })
  return [
    casing('track-past', past, TRACK_WIDTH.past),
    casing('track-future', later, TRACK_WIDTH.later),
    casing('track-next', soon, TRACK_WIDTH.next),
    new PathLayer<CycloneTrackPoint[]>({
      id: 'track-past',
      data: past,
      getPath: (d) => d.map(lonLat),
      getColor: TRACK_COLOR,
      widthUnits: 'pixels',
      getWidth: TRACK_WIDTH.past,
      capRounded: true,
      jointRounded: true,
    }),
    new PathLayer<CycloneTrackPoint[], PathStyleExtensionProps<CycloneTrackPoint[]>>({
      id: 'track-future',
      data: later,
      getPath: (d) => d.map(lonLat),
      getColor: TRACK_FUTURE_COLOR,
      widthUnits: 'pixels',
      getWidth: TRACK_WIDTH.later,
      getDashArray: [6, 5],
      dashJustified: true,
      extensions: [new PathStyleExtension({ dash: true })],
    }),
    new PathLayer<CycloneTrackPoint[]>({
      id: 'track-next',
      data: soon,
      getPath: (d) => d.map(lonLat),
      getColor: TRACK_NEXT_COLOR,
      widthUnits: 'pixels',
      getWidth: TRACK_WIDTH.next,
      capRounded: true,
      jointRounded: true,
    }),
    // The current position: a static halo under the storm dot (no animation, no redraws).
    new ScatterplotLayer<CycloneTrackPoint>({
      id: 'track-storm-halo',
      data: [current],
      pickable: false,
      getPosition: lonLat,
      radiusUnits: 'pixels',
      getRadius: 12,
      getFillColor: STORM_HALO,
    }),
    new ScatterplotLayer<CycloneTrackPoint>({
      id: 'track-storm',
      data: [current],
      pickable: true,
      getPosition: lonLat,
      radiusUnits: 'pixels',
      getRadius: 6,
      getFillColor: STORM_FILL,
      stroked: true,
      getLineColor: STORM_OUTLINE,
      lineWidthUnits: 'pixels',
      getLineWidth: 2,
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
  if (id === 'hazard-isotachs') {
    const line = info.object as Isotach
    return `Isotach ${line.kmh} km/h: ${line.category}`
  }
  if (id !== 'hazard-cells') return null
  const v = info.object as CellValues
  const lines: string[] = []
  if (v.surge !== null && v.surge > SURGE_MIN_M) {
    lines.push(`Storm surge ${v.surge.toFixed(1)} m above ground`)
  }
  if (v.wind !== null) {
    const kmh = toKmh(v.wind)
    lines.push(`Wind ${Math.round(kmh)} km/h, ${imdCategory(kmh)?.name ?? 'below depression'}`)
  }
  if (v.flood !== null) lines.push(`Flood susceptibility ${v.flood.toFixed(2)} (static)`)
  return lines.length ? lines.join('\n') : null
}
