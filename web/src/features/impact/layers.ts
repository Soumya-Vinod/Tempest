// deck.gl layers for affected infrastructure. They sit above the exposure layers; unaffected
// features aren't drawn here at all, so the exposure styling shows through unchanged.
import type { Color, Layer, PickingInfo } from '@deck.gl/core'
import { GeoJsonLayer, IconLayer, ScatterplotLayer } from '@deck.gl/layers'
import type { Feature, Geometry } from 'geojson'

import type {
  ImpactResult,
  ImpactResultProperties,
  ImpactStatus,
  InfraGeometry,
} from '../../types/contracts'
import { IMPACT_COLOR, PULSE_MS, RADIUS, STATUS_RANK, WIDTH } from './style'

/** One affected infra feature: its worst status and every non-ok row (one per hazard). */
export interface Affected {
  id: string
  geometry: InfraGeometry
  worst: ImpactStatus
  rows: ImpactResultProperties[]
}

/** Group non-ok rows by infra feature, worst row first. */
export function aggregate(results: ImpactResult[]): Map<string, Affected> {
  const out = new Map<string, Affected>()
  for (const r of results) {
    const p = r.properties
    const a = out.get(p.infra_id)
    if (!a) {
      out.set(p.infra_id, { id: p.infra_id, geometry: r.geometry, worst: p.status, rows: [p] })
      continue
    }
    a.rows.push(p)
    if (STATUS_RANK[p.status] > STATUS_RANK[a.worst]) a.worst = p.status
  }
  for (const a of out.values()) a.rows.sort((x, y) => STATUS_RANK[y.status] - STATUS_RANK[x.status])
  return out
}

type AffectedFeature = Feature<Geometry, { affected: Affected }>

const asFeature = (a: Affected): AffectedFeature => ({
  type: 'Feature',
  geometry: a.geometry as Geometry,
  properties: { affected: a },
})

const isRoad = (a: Affected) => a.id.startsWith('road-')

function lineColor(f: AffectedFeature): Color {
  return f.properties.affected.worst === 'cut' ? IMPACT_COLOR.cut : IMPACT_COLOR.atRisk
}

function lineWidth(f: AffectedFeature): number {
  const a = f.properties.affected
  if (!isRoad(a)) return WIDTH.powerLineAtRisk
  return a.worst === 'cut' ? WIDTH.roadCut : WIDTH.roadAtRisk
}

const pointFill = (f: AffectedFeature): Color =>
  f.properties.affected.worst === 'cut' ? IMPACT_COLOR.cut : IMPACT_COLOR.atRisk

const position = (a: Affected) => a.geometry.coordinates as [number, number]
const pulseMax = () => RADIUS.isolatedMax
const pulseMin = () => RADIUS.isolatedMin

export interface ImpactLayerData {
  lines: AffectedFeature[]
  points: AffectedFeature[] // at_risk / cut points (substations, facilities)
  isolated: Affected[] // cut off now: solid, pulsing ring
  expected: Affected[] // expected within 24 h, not yet (v1.3): dashed ring
}

/**
 * Split once per result set; layers are rebuilt from these stable arrays. `isolatedNow` (at
 * horizon 24: what is isolated at horizon 0) separates expected isolation from the actual one;
 * null at horizon 0, where every isolated feature is cut off now.
 */
export function layerData(
  affected: Map<string, Affected>,
  isolatedNow: Set<string> | null = null,
): ImpactLayerData {
  const lines: AffectedFeature[] = []
  const points: AffectedFeature[] = []
  const isolated: Affected[] = []
  const expected: Affected[] = []
  for (const a of affected.values()) {
    if (a.geometry.type !== 'Point') lines.push(asFeature(a))
    else if (a.worst !== 'isolated') points.push(asFeature(a))
    else if (isolatedNow && !isolatedNow.has(a.id)) expected.push(a)
    else isolated.push(a)
  }
  return { lines, points, isolated, expected }
}

// A dashed ring (deck.gl circles can't be dashed): an SVG icon in the isolated colour.
const [ir, ig, ib] = IMPACT_COLOR.isolated
const DASHED_RING = {
  id: 'expected-ring',
  url:
    'data:image/svg+xml;charset=utf-8,' +
    encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">` +
        `<circle cx="32" cy="32" r="26" fill="rgba(${ir},${ig},${ib},0.12)" ` +
        `stroke="rgb(${ir},${ig},${ib})" stroke-width="5" stroke-dasharray="9 7"/></svg>`,
    ),
  width: 64,
  height: 64,
}

const HIGHLIGHT_LINE: Color = [...IMPACT_COLOR.highlight, 230]
const AUTO_HIGHLIGHT: number[] = [250, 204, 21, 200]

/**
 * Impact layers, bottom to top: lines, points, isolated rings; and, separately, the highlight
 * (drawn above the storm track with the other selection highlights).
 */
export function buildImpactLayers(
  data: ImpactLayerData,
  highlight: InfraGeometry | null,
  pulse: boolean,
): { layers: Layer[]; highlight: Layer[] } {
  const layers: Layer[] = [
    new GeoJsonLayer<{ affected: Affected }>({
      id: 'impact-lines',
      data: { type: 'FeatureCollection', features: data.lines },
      pickable: true,
      autoHighlight: true,
      highlightColor: AUTO_HIGHLIGHT,
      lineWidthUnits: 'pixels',
      getLineColor: lineColor,
      getLineWidth: lineWidth,
    }),
    new GeoJsonLayer<{ affected: Affected }>({
      id: 'impact-points',
      data: { type: 'FeatureCollection', features: data.points },
      pickable: true,
      autoHighlight: true,
      highlightColor: AUTO_HIGHLIGHT,
      pointType: 'circle',
      pointRadiusUnits: 'pixels',
      getPointRadius: RADIUS.atRisk,
      getFillColor: pointFill,
      stroked: true,
      lineWidthUnits: 'pixels',
      getLineColor: IMPACT_COLOR.outline,
      getLineWidth: 1,
    }),
    // Pulsing: only the target radius changes (every PULSE_MS); deck.gl animates the
    // transition on the GPU, so there's no per-frame React work.
    new IconLayer<Affected>({
      id: 'impact-expected',
      data: data.expected,
      pickable: true,
      getPosition: position,
      getIcon: () => DASHED_RING,
      sizeUnits: 'pixels',
      getSize: 2 * RADIUS.isolatedMax,
    }),
    new ScatterplotLayer<Affected>({
      id: 'impact-isolated',
      data: data.isolated,
      pickable: true,
      getPosition: position,
      radiusUnits: 'pixels',
      // An accessor (not a constant) so the radius is a buffer that transitions can interpolate.
      getRadius: pulse ? pulseMax : pulseMin,
      updateTriggers: { getRadius: pulse },
      stroked: true,
      filled: true,
      getFillColor: IMPACT_COLOR.isolatedFill,
      getLineColor: IMPACT_COLOR.isolated,
      lineWidthUnits: 'pixels',
      getLineWidth: 3,
      transitions: { getRadius: { duration: PULSE_MS } },
    }),
  ]
  const highlightLayers: Layer[] = []
  if (highlight) {
    highlightLayers.push(
      new GeoJsonLayer({
        id: 'impact-highlight',
        data: { type: 'Feature', geometry: highlight as Geometry, properties: {} },
        pickable: false,
        lineWidthUnits: 'pixels',
        getLineWidth: WIDTH.highlight,
        getLineColor: HIGHLIGHT_LINE,
        pointType: 'circle',
        pointRadiusUnits: 'pixels',
        getPointRadius: RADIUS.highlight,
        filled: false,
        stroked: true,
      }),
    )
  }
  return { layers, highlight: highlightLayers }
}

/** The Affected under a click or hover on an impact layer, if any. */
export function pickedAffected(info: PickingInfo): Affected | null {
  const id = info.layer?.id ?? ''
  if (!info.object || !id.startsWith('impact-')) return null
  if (id === 'impact-isolated' || id === 'impact-expected') return info.object as Affected
  return (info.object as AffectedFeature).properties.affected
}
