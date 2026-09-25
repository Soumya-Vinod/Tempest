// deck.gl layers for InfraFeatures. Accessors are module-level functions with no captured state,
// so rebuilding a layer (e.g. a visibility toggle) never makes deck.gl recompute attributes:
// only `visible` changes and the GPU buffers are reused, which keeps panning smooth.
import type { Color, Layer } from '@deck.gl/core'
import { GeoJsonLayer, type GeoJsonLayerProps } from '@deck.gl/layers'
import type { Feature, Geometry } from 'geojson'

import type {
  InfraFeatureCollection,
  InfraFeatureProperties,
  InfraType,
} from '../../types/contracts'
import type { InfraByType } from './useInfra'
import {
  COLOR,
  FERRY_WIDTH,
  FULL_SIZE_M_PER_PX,
  LINK_WIDTH,
  MAJOR_ROADS,
  OUTLINE_PX,
  POINT_PX,
  ROAD_WIDTH,
  SCHOOL_RING_PX,
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

function roadWidth(f: InfraGeoFeature): number {
  if (isFerry(f)) return FERRY_WIDTH
  const hw = highway(f)
  if (hw.endsWith('_link')) return LINK_WIDTH
  return ROAD_WIDTH[hw] ?? ROAD_WIDTH.unclassified
}

const isSchoolProxy = (f: InfraGeoFeature) => attr(f, 'shelter_kind') === 'school_proxy'

const shelterFill = (f: InfraGeoFeature): Color =>
  isSchoolProxy(f) ? COLOR.schoolFill : COLOR.shelter
const shelterLine = (f: InfraGeoFeature): Color =>
  isSchoolProxy(f) ? COLOR.shelter : COLOR.outline
const shelterLineWidth = (f: InfraGeoFeature) => (isSchoolProxy(f) ? SCHOOL_RING_PX : OUTLINE_PX)

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
  'getFillColor' | 'getLineColor' | 'getLineWidth'
>

/** Points sized in metres, clamped to [min, max] px: small at AOI zoom, full size zoomed in. */
function pointLayer(
  id: string,
  data: InfraFeatureCollection,
  visible: boolean,
  [minPx, maxPx]: readonly [number, number],
  style: PointStyle,
) {
  return new GeoJsonLayer<InfraFeatureProperties>({
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

/** Layers bottom to top: roads, power lines, then points (hospitals on top). */
export function buildInfraLayers(
  state: InfraByType,
  visible: Record<InfraType, boolean>,
): Layer[] {
  const data = (t: InfraType) => {
    const s = state[t]
    return s.status === 'ok' ? s.data : EMPTY
  }
  const [hospitals, healthCentres] = splitHealth(data('hospital'))
  const outlined = (fill: Color): PointStyle => ({
    getFillColor: fill,
    getLineColor: COLOR.outline,
    getLineWidth: OUTLINE_PX,
  })
  return [
    new GeoJsonLayer<InfraFeatureProperties>({
      id: 'infra-road',
      data: data('road'),
      visible: visible.road,
      ...COMMON,
      getLineColor: roadColor,
      getLineWidth: roadWidth,
      lineWidthMinPixels: 1,
    }),
    new GeoJsonLayer<InfraFeatureProperties>({
      id: 'infra-power_line',
      data: data('power_line'),
      visible: visible.power_line,
      ...COMMON,
      getLineColor: COLOR.powerLine,
      getLineWidth: 1.2,
    }),
    pointLayer(
      'infra-substation',
      data('substation'),
      visible.substation,
      POINT_PX.substation,
      outlined(COLOR.substation),
    ),
    pointLayer('infra-shelter', data('shelter'), visible.shelter, POINT_PX.shelter, {
      getFillColor: shelterFill,
      getLineColor: shelterLine,
      getLineWidth: shelterLineWidth,
    }),
    pointLayer(
      'infra-health-centre',
      healthCentres,
      visible.hospital,
      POINT_PX.healthCentre,
      outlined(COLOR.healthCentre),
    ),
    pointLayer(
      'infra-hospital',
      hospitals,
      visible.hospital,
      POINT_PX.hospital,
      outlined(COLOR.hospital),
    ),
  ]
}
