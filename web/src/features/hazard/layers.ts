// deck.gl layers for the hazard view (flood, surge, wind cells) and the storm track (both views).
import type { Color, Layer, PickingInfo } from '@deck.gl/core'
import {
  MaskExtension,
  type MaskExtensionProps,
  PathStyleExtension,
  type PathStyleExtensionProps,
} from '@deck.gl/extensions'
import {
  BitmapLayer,
  type BitmapLayerProps,
  GeoJsonLayer,
  PathLayer,
  PolygonLayer,
  ScatterplotLayer,
  TextLayer,
} from '@deck.gl/layers'
import type { Feature } from 'geojson'

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
  STORM_OUTLINE,
  SURGE_MIN_M,
  surgePixel,
  toKmh,
  TRACK_COLOR,
  TRACK_FUTURE_COLOR,
} from './style'

const EMPTY = { type: 'FeatureCollection' as const, features: [] as HazardLayer[] }
const collection = (features: HazardLayer[]) => ({ ...EMPTY, features })

// Land mask: South 24 Parganas + Kolkata land (unfilled OSM districts), bundled simplified.
// Generated from api/data/reference/s24p_land.geojson (351 KB): union, simplify 100 m in UTM 45N
// (EPSG:32645, topology kept), round to 1e-4°, GeoJSON Feature, 52 KB, 90 parts, area within
// 0.04 %. Nothing is drawn or pickable outside it: not over the sea, rivers, N 24 Parganas or
// Bangladesh.
const LAND_MASK_ID = 'hazard-land-mask'
const MASK = { extensions: [new MaskExtension()], maskId: LAND_MASK_ID }
const LINEAR: BitmapLayerProps['textureParameters'] = {
  minFilter: 'linear',
  magFilter: 'linear',
}
// Nearly transparent: deck.gl picks it, the eye doesn't see it.
const PICK_ONLY: Color = [0, 0, 0, 1]

function landMask(): Layer {
  return new GeoJsonLayer({ id: LAND_MASK_ID, data: land as Feature, operation: 'mask' })
}

/** A smoothed, land-masked image of one hazard (null data: hidden). */
function imageLayer(id: string, cells: HazardLayer[] | null, colorize: Colorize): Layer[] {
  const img = cells ? hazardImage(cells, colorize) : null
  if (!img) return []
  return [
    new BitmapLayer({
      id,
      image: img.image,
      bounds: img.bounds,
      textureParameters: LINEAR,
      pickable: false,
      ...MASK,
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
export function buildHazardFills(cells: {
  flood: HazardLayer[] | null
  surge: HazardLayer[] | null
  wind: HazardLayer[] | null
}): Layer[] {
  const layers: Layer[] = [landMask()]
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
  if (cells.surge) layers.push(...imageLayer('hazard-surge-image', cells.surge, surgePixel))
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
        fontWeight: 600,
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
