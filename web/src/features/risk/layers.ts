// deck.gl layers for the risk choropleth: blocks, an invisible pick layer for the unscored areas
// (their hatching is a MapLibre layer, hatch.ts), and the selected block's outline.
import type { Layer, PickingInfo } from '@deck.gl/core'
import { GeoJsonLayer } from '@deck.gl/layers'
import type { Feature, Geometry } from 'geojson'

import type {
  RiskScore,
  RiskScoreCollection,
  RiskScoreProperties,
  UnscoredAreaCollection,
  UnscoredAreaProperties,
} from '../../types/contracts'
import { FILL_ALPHA, OUTLINE, riskColor, SELECTED_OUTLINE, UNSCORED_PICK } from './style'

type BlockFeature = Feature<Geometry, RiskScoreProperties>

const blockFill = (f: BlockFeature) => riskColor(f.properties.score, FILL_ALPHA)

export function buildRiskLayers(
  scores: RiskScoreCollection | null,
  unscored: UnscoredAreaCollection | null,
  selected: RiskScore | null,
  visible: boolean,
): Layer[] {
  const layers: Layer[] = [
    new GeoJsonLayer<RiskScoreProperties>({
      id: 'risk-blocks',
      data: scores ?? { type: 'FeatureCollection', features: [] },
      visible,
      pickable: true,
      filled: true,
      getFillColor: blockFill,
      stroked: true,
      lineWidthUnits: 'pixels',
      getLineColor: OUTLINE,
      getLineWidth: 1,
    }),
    new GeoJsonLayer<UnscoredAreaProperties>({
      id: 'risk-unscored',
      data: unscored ?? { type: 'FeatureCollection', features: [] },
      visible,
      pickable: true,
      filled: true,
      getFillColor: UNSCORED_PICK,
      stroked: false,
    }),
  ]
  if (selected && visible) {
    layers.push(
      new GeoJsonLayer({
        id: 'risk-selected',
        data: selected,
        pickable: false,
        filled: false,
        stroked: true,
        lineWidthUnits: 'pixels',
        getLineColor: SELECTED_OUTLINE,
        getLineWidth: 3,
      }),
    )
  }
  return layers
}

/** The block (or unscored area) under a click or hover, if any. */
export function pickedBlock(info: PickingInfo): RiskScore | null {
  return info.object && info.layer?.id === 'risk-blocks' ? (info.object as RiskScore) : null
}

export function pickedUnscored(info: PickingInfo): boolean {
  return Boolean(info.object) && info.layer?.id === 'risk-unscored'
}
