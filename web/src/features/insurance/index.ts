// Insurance feature (Dev B): illustrative parametric triggers per CD block. The panel section,
// and in the Risk view a gold outline on blocks with a payout released.
import type { Layer } from '@deck.gl/core'
import { GeoJsonLayer } from '@deck.gl/layers'
import { useMemo } from 'react'

import { REPLAY_TIMESTEPS } from '../../lib/constants'
import type { InsurancePanelProps } from './InsurancePanel'
import { useInsuranceSummary, useTriggers } from './useInsurance'

export { default as InsurancePanel } from './InsurancePanel'

const GOLD: [number, number, number, number] = [202, 138, 4, 255]

export interface InsuranceMap {
  /** Gold outlines on paying blocks (Risk view only), above the choropleth. */
  layers: Layer[]
  panel: InsurancePanelProps
}

export function useInsuranceMap(timestepIndex: number, riskView: boolean): InsuranceMap {
  const { state, shown } = useTriggers(REPLAY_TIMESTEPS[timestepIndex])
  const summary = useInsuranceSummary()
  const layers = useMemo(() => {
    const paying = shown.filter((f) => f.properties.released_tier > 0)
    return [
      new GeoJsonLayer({
        id: 'insurance-paying',
        data: { type: 'FeatureCollection', features: paying },
        visible: riskView,
        pickable: false,
        filled: false,
        stroked: true,
        lineWidthUnits: 'pixels',
        getLineWidth: 2.5,
        getLineColor: GOLD,
      }),
    ]
  }, [shown, riskView])
  return { layers, panel: { timestepIndex, triggers: state, shown, summary } }
}
