// Insurance feature (Dev B): illustrative parametric triggers per CD block. The panel section,
// and, while the Finance tab is open, a gold outline on blocks with a payout released.
import type { Layer } from '@deck.gl/core'
import { lazy, useMemo } from 'react'

import { useDeck } from '../../lib/deck'
import { useTimeline } from '../../lib/timeline'
import type { InsurancePanelProps } from './InsurancePanel'
import { useInsuranceSummary, useTriggers } from './useInsurance'

// Code-split: loaded the first time it is shown (see components/Deferred).
export const InsurancePanel = lazy(() => import('./InsurancePanel'))

const GOLD: [number, number, number, number] = [202, 138, 4, 255]

export interface InsuranceMap {
  /** Gold outlines on paying blocks (while the Finance tab is open), above the choropleth. */
  layers: Layer[]
  panel: InsurancePanelProps
}

export function useInsuranceMap(timestepIndex: number, outlined: boolean): InsuranceMap {
  const { state, shown } = useTriggers(useTimeline().timesteps[timestepIndex])
  const summary = useInsuranceSummary()
  const deck = useDeck()
  const layers = useMemo(() => {
    if (!deck) return []
    const paying = shown.filter((f) => f.properties.released_tier > 0)
    return [
      new deck.GeoJsonLayer({
        id: 'insurance-paying',
        data: { type: 'FeatureCollection', features: paying },
        visible: outlined,
        pickable: false,
        filled: false,
        stroked: true,
        lineWidthUnits: 'pixels',
        getLineWidth: 2.5,
        getLineColor: GOLD,
      }),
    ]
  }, [deck, shown, outlined])
  return { layers, panel: { timestepIndex, triggers: state, shown, summary } }
}
