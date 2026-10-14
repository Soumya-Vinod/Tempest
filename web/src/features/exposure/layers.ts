// deck.gl layers for InfraFeatures. Accessors are module-level functions with no captured state,
// so rebuilding a layer (e.g. a visibility toggle) never makes deck.gl recompute attributes:
// only `visible` changes and the GPU buffers are reused, which keeps panning smooth.
import type { Color, Layer } from '@deck.gl/core'
import type { PathStyleExtensionProps } from '@deck.gl/extensions'
import type { GeoJsonLayerProps } from '@deck.gl/layers'
import type { Feature, Geometry } from 'geojson'

import type { Deck } from '../../lib/deck'
import type {
  InfraFeatureCollection,
  InfraFeatureProperties,
  InfraType,
} from '../../types/contracts'
import type { InfraByType } from './useInfra'
import {
  COLOR,
  DETAIL_ZOOM,
  FERRY_WIDTH,
  FULL_SIZE_M_PER_PX,
  LINK_WIDTH,
  MAJOR_ROADS,
  MUTED,
  OUTLINE_PX,
  OVERVIEW_ROADS,
  POINT_PX,
  POWER_LINE_OPACITY,
  ROAD_OPACITY,
  ROAD_WIDTH,
  roadWidthScale,
  STAND_IN,
  STAND_IN_RING_PX,
} from './style'

type InfraGeoFeature = Feature<Geometry, InfraFeatureProperties>

const attr = (f: InfraGeoFeature, key: string): unknown => f.properties.attributes[key]
const highway = (f: InfraGeoFeature) => String(attr(f, 'highway') ?? '')
const isFerry = (f: InfraGeoFeature) => attr(f, 'ferry') === true
/** Roads flagged by the ingest as not reachable from the main road component at baseline. */
const noMainland = (f: InfraGeoFeature) => attr(f, 'baseline_reachable_from_main') === false

function roadColor(f: InfraGeoFeature): Color {
  if (noMainland(f)) return COLOR.noMainland
  if (isFerry(f)) return COLOR.ferry
  return MAJOR_ROADS.has(highway(f).replace(/_link$/, '')) ? COLOR.roadMajor : COLOR.roadMinor
}

function mutedRoadColor(f: InfraGeoFeature): Color {
  if (noMainland(f)) return MUTED.noMainland
  if (isFerry(f)) return MUTED.ferry
  const hw = highway(f).replace(/_link$/, '')
  if (MAJOR_ROADS.has(hw)) return MUTED.roadMajor
  return hw === 'secondary' || hw === 'tertiary' ? MUTED.roadMid : MUTED.roadMinor
}

// Dash patterns, in line widths: ferries dashed, power lines dotted, everything else solid.
const SOLID: [number, number] = [0, 0]
const FERRY_DASH: [number, number] = [3, 2]
const POWER_DOTS: [number, number] = [1, 2]
const roadDash = (f: InfraGeoFeature): [number, number] => (isFerry(f) ? FERRY_DASH : SOLID)

function roadWidth(f: InfraGeoFeature): number {
  if (isFerry(f)) return FERRY_WIDTH
  const hw = highway(f)
  if (hw.endsWith('_link')) return LINK_WIDTH
  return ROAD_WIDTH[hw] ?? ROAD_WIDTH.unclassified
}

// Roads split once per loaded collection: the overview classes (and ferries) at every zoom, the
// rest only from DETAIL_ZOOM, so the district view isn't a dense web (around Kolkata).
type RoadPair = [overview: InfraFeatureCollection, detail: InfraFeatureCollection]
const roadSplit = new WeakMap<InfraFeatureCollection, RoadPair>()

function splitRoads(fc: InfraFeatureCollection): RoadPair {
  let pair = roadSplit.get(fc)
  if (!pair) {
    const overview = (f: InfraFeatureCollection['features'][number]) =>
      isFerry(f as InfraGeoFeature) || OVERVIEW_ROADS.has(highway(f as InfraGeoFeature))
    pair = [
      { type: 'FeatureCollection', features: fc.features.filter(overview) },
      { type: 'FeatureCollection', features: fc.features.filter((f) => !overview(f)) },
    ]
    roadSplit.set(fc, pair)
  }
  return pair
}

/** The stand-in style for a *_proxy shelter_kind, or undefined for a real shelter. */
const standIn = (f: InfraGeoFeature) => STAND_IN[String(attr(f, 'shelter_kind'))]

const shelterFill = (f: InfraGeoFeature): Color => (standIn(f) ? COLOR.standInFill : COLOR.shelter)
const shelterLine = (f: InfraGeoFeature): Color => standIn(f)?.ring ?? COLOR.outline
const shelterLineWidth = (f: InfraGeoFeature) => (standIn(f) ? STAND_IN_RING_PX : OUTLINE_PX)
const mutedShelterFill = (f: InfraGeoFeature): Color =>
  standIn(f) ? COLOR.standInFill : MUTED.shelter
const mutedShelterLine = (f: InfraGeoFeature): Color =>
  standIn(f) ? MUTED.standInRing : COLOR.outline

const HIGHLIGHT: number[] = [250, 204, 21, 200] // yellow-400

const COMMON = {
  pickable: true,
  autoHighlight: true,
  highlightColor: HIGHLIGHT,
  lineWidthUnits: 'pixels' as const,
  pointType: 'circle',
}

const EMPTY: InfraFeatureCollection = { type: 'FeatureCollection', features: [] }

// Hospitals and health centres are separate layers: pixel clamps are per layer, so one layer
// would clamp both to the same size when zoomed out. Split once per loaded collection.
type Pair = [hospitals: InfraFeatureCollection, healthCentres: InfraFeatureCollection]
const healthSplit = new WeakMap<InfraFeatureCollection, Pair>()

function splitHealth(fc: InfraFeatureCollection): Pair {
  let pair = healthSplit.get(fc)
  if (!pair) {
    const isHospital = (f: InfraFeatureCollection['features'][number]) =>
      f.properties.attributes.facility_level === 'hospital'
    pair = [
      { type: 'FeatureCollection', features: fc.features.filter(isHospital) },
      { type: 'FeatureCollection', features: fc.features.filter((f) => !isHospital(f)) },
    ]
    healthSplit.set(fc, pair)
  }
  return pair
}

type PointStyle = Pick<
  GeoJsonLayerProps<InfraFeatureProperties>,
  'getFillColor' | 'getLineColor' | 'getLineWidth' | 'updateTriggers'
>

/** Points sized in metres, clamped to [min, max] px: small at AOI zoom, full size zoomed in. */
function pointLayer(
  deck: Deck,
  id: string,
  data: InfraFeatureCollection,
  visible: boolean,
  [minPx, maxPx]: readonly [number, number],
  style: PointStyle,
) {
  return new deck.GeoJsonLayer<InfraFeatureProperties>({
    id,
    data,
    visible,
    ...COMMON,
    pointRadiusUnits: 'meters',
    getPointRadius: maxPx * FULL_SIZE_M_PER_PX,
    pointRadiusMinPixels: minPx,
    pointRadiusMaxPixels: maxPx,
    stroked: true,
    ...style,
  })
}

/**
 * Which facility points (health facilities and shelters) get the full style; the rest are drawn
 * quiet (small, faint, no outline) so the map is never empty. null: every facility in full.
 */
export type FacilityFilter = ((f: InfraFeatureCollection['features'][number]) => boolean) | null

type Split = { full: InfraFeatureCollection; quiet: InfraFeatureCollection }
// Split collections, per source collection and filter: rebuilt only when either changes.
const splits = new WeakMap<InfraFeatureCollection, { filter: FacilityFilter; split: Split }>()

function split(fc: InfraFeatureCollection, filter: FacilityFilter): Split {
  if (!filter) return { full: fc, quiet: EMPTY }
  const hit = splits.get(fc)
  if (hit && hit.filter === filter) return hit.split
  const full: InfraFeatureCollection['features'] = []
  const quiet: InfraFeatureCollection['features'] = []
  for (const f of fc.features) (filter(f) ? full : quiet).push(f)
  const out = {
    full: { type: 'FeatureCollection' as const, features: full },
    quiet: { type: 'FeatureCollection' as const, features: quiet },
  }
  splits.set(fc, { filter, split: out })
  return out
}

const QUIET_OPACITY = 0.25
// [floor, full] radius in px. Their 100 m radius is under 1 px at the district view (below about
// zoom 11), so the floor sets the size there: 1 px keeps dense areas (Kolkata) a faint stipple
// instead of a dark blob. They grow to full size from about zoom 12.
const QUIET_PX: readonly [number, number] = [1, 4]

/** Facilities outside the affected area: small, faint, no outline (still hoverable). */
function quietLayer(
  deck: Deck,
  id: string,
  data: InfraFeatureCollection,
  visible: boolean,
  fill: Color,
) {
  return new deck.GeoJsonLayer<InfraFeatureProperties>({
    id,
    data,
    visible,
    ...COMMON,
    pointRadiusUnits: 'meters',
    getPointRadius: QUIET_PX[1] * FULL_SIZE_M_PER_PX,
    pointRadiusMinPixels: QUIET_PX[0],
    pointRadiusMaxPixels: QUIET_PX[1],
    stroked: false,
    getFillColor: fill,
    opacity: QUIET_OPACITY,
  })
}

/** Layers bottom to top: roads, power lines, then points (hospitals on top). */
export function buildInfraLayers(
  deck: Deck,
  state: InfraByType,
  visible: Record<InfraType, boolean>,
  muted = false,
  facilities: FacilityFilter = null,
  zoom = DETAIL_ZOOM,
): Layer[] {
  // Colour accessors are fixed functions; updateTriggers make deck.gl recolour only when `muted`
  // flips, never on other rebuilds.
  const colours = { getLineColor: muted, getFillColor: muted }
  const { GeoJsonLayer, PathStyleExtension } = deck
  const dashed = { extensions: [new PathStyleExtension({ dash: true })], dashJustified: true }
  const palette = muted ? MUTED : COLOR
  const data = (t: InfraType) => {
    const s = state[t]
    return s.status === 'ok' ? s.data : EMPTY
  }
  const [allHospitals, allHealthCentres] = splitHealth(data('hospital'))
  const hospitals = split(allHospitals, facilities)
  const healthCentres = split(allHealthCentres, facilities)
  const shelters = split(data('shelter'), facilities)
  const [overviewRoads, detailRoads] = splitRoads(data('road'))
  const road = (id: string, fc: InfraFeatureCollection, show: boolean) =>
    new GeoJsonLayer<InfraFeatureProperties, PathStyleExtensionProps<InfraGeoFeature>>({
      id,
      data: fc,
      visible: show,
      ...COMMON,
      getLineColor: muted ? mutedRoadColor : roadColor,
      updateTriggers: colours,
      getLineWidth: roadWidth,
      lineWidthScale: roadWidthScale(zoom),
      lineWidthMinPixels: 0.75,
      opacity: ROAD_OPACITY,
      getDashArray: roadDash,
      ...dashed,
    })
  const outlined = (fill: Color): PointStyle => ({
    getFillColor: fill,
    getLineColor: COLOR.outline,
    getLineWidth: OUTLINE_PX,
  })
  return [
    road('infra-road-detail', detailRoads, visible.road && zoom >= DETAIL_ZOOM),
    road('infra-road', overviewRoads, visible.road),
    new GeoJsonLayer<InfraFeatureProperties, PathStyleExtensionProps<InfraGeoFeature>>({
      id: 'infra-power_line',
      data: data('power_line'),
      visible: visible.power_line,
      ...COMMON,
      getLineColor: palette.powerLine,
      getLineWidth: 1,
      opacity: POWER_LINE_OPACITY,
      getDashArray: POWER_DOTS,
      ...dashed,
    }),
    pointLayer(
      deck,
      'infra-substation',
      data('substation'),
      visible.substation,
      POINT_PX.substation,
      outlined(palette.substation),
    ),
    // Quiet facilities first, under the full-style ones.
    quietLayer(deck, 'infra-shelter-quiet', shelters.quiet, visible.shelter, palette.shelter),
    quietLayer(deck, 'infra-health-centre-quiet', healthCentres.quiet, visible.hospital, palette.healthCentre),
    quietLayer(deck, 'infra-hospital-quiet', hospitals.quiet, visible.hospital, palette.hospital),
    pointLayer(deck, 'infra-shelter', shelters.full, visible.shelter, POINT_PX.shelter, {
      getFillColor: muted ? mutedShelterFill : shelterFill,
      getLineColor: muted ? mutedShelterLine : shelterLine,
      getLineWidth: shelterLineWidth,
      updateTriggers: colours,
    }),
    pointLayer(
      deck,
      'infra-health-centre',
      healthCentres.full,
      visible.hospital,
      POINT_PX.healthCentre,
      outlined(palette.healthCentre),
    ),
    pointLayer(
      deck,
      'infra-hospital',
      hospitals.full,
      visible.hospital,
      POINT_PX.hospital,
      outlined(palette.hospital),
    ),
  ]
}
