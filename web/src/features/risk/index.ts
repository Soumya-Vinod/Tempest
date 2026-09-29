// Risk feature (Dev B): the "Risk by block" choropleth, unscored areas, block card and panel.
import type { DeckProps, Layer, PickingInfo } from '@deck.gl/core'
import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { REPLAY_TIMESTEPS, RISK_VIEW_MIN_SCORE } from '../../lib/constants'
import type { Horizon } from '../../types/contracts'
import type { MapViewMode } from '../hazard'
import { syncUnscored } from './hatch'
import { buildRiskLayers, pickedBlock, pickedUnscored } from './layers'
import type { RiskCardProps } from './RiskCard'
import type { SurgeHeadlineProps } from './SurgeHeadline'
import { DRIVER_LABEL } from './style'
import { type RiskState, useRisk, useUnscoredAreas } from './useRisk'

export { default as RiskCard } from './RiskCard'
export { default as RiskPanel } from './RiskPanel'
export { default as SurgeHeadline, type SurgeHeadlineProps } from './SurgeHeadline'

type TooltipContent = ReturnType<NonNullable<DeckProps['getTooltip']>>

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

export interface RiskMap {
  /** The effective map view: the user's choice, or automatic (see useRiskMap). */
  view: MapViewMode
  /** The choropleth (fills slot, below exposure); hidden in the Hazard view. */
  layers: Layer[]
  /** The selected block's outline, drawn above everything else. */
  highlightLayers: Layer[]
  tooltip: (info: PickingInfo) => TooltipContent
  /** Selects the clicked block (true) or clears the selection (false). */
  onClick: (info: PickingInfo) => boolean
  clear: () => void
  /** Selects a block by id (e.g. from the advisory queue); the caller switches to the Risk view. */
  select: (blockId: string) => void
  /** Every scored block, for pickers. */
  blocks: { block_id: string; block_name: string }[]
  onMapLoad: (map: MapLibreMap) => void
  panel: { visible: boolean; state: RiskState }
  card: RiskCardProps
  /** District people-in-surge headline (v1.3), for the current horizon. */
  surge: SurgeHeadlineProps
}

/**
 * Risk for the scrubber's timestep. `chosenView` is the user's explicit Hazard / Risk choice, or
 * null: then the view is Risk once any block at this timestep scores RISK_VIEW_MIN_SCORE or more
 * (the advisory threshold), else Hazard. The selection only applies in the Risk view.
 */
export function useRiskMap(
  timestepIndex: number,
  chosenView: MapViewMode | null,
  horizon: Horizon = 0,
): RiskMap {
  const timestep = REPLAY_TIMESTEPS[timestepIndex]
  // v1.3: at horizon 24 the scores are on the expected hazard (the next 24 h), so the Risk view
  // turns on (automatically) as soon as a block is expected to reach the threshold.
  const { state, shown } = useRisk(timestep, horizon)
  const unscored = useUnscoredAreas()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [map, setMap] = useState<MapLibreMap | null>(null)

  const anyAtRisk = useMemo(
    () => shown?.scores.features.some((f) => f.properties.score >= RISK_VIEW_MIN_SCORE) ?? false,
    [shown],
  )
  const view: MapViewMode = chosenView ?? (anyAtRisk ? 'risk' : 'hazard')
  const visible = view === 'risk'

  const selected = useMemo(
    () =>
      visible
        ? (shown?.scores.features.find((f) => f.properties.block_id === selectedId) ?? null)
        : null,
    [shown, selectedId, visible],
  )
  const breakdown = useMemo(
    () => shown?.breakdown?.blocks.find((b) => b.block_id === selectedId) ?? null,
    [shown, selectedId],
  )

  const { layers, highlight: highlightLayers } = useMemo(
    () => buildRiskLayers(shown?.scores ?? null, unscored, selected, visible),
    [shown, unscored, selected, visible],
  )

  // Hatched unscored areas live in MapLibre (fill-pattern); keep them in sync with the toggle.
  useEffect(() => {
    if (map && unscored) syncUnscored(map, unscored, visible)
  }, [map, unscored, visible])

  const clear = useCallback(() => setSelectedId(null), [])
  const select = useCallback((blockId: string) => setSelectedId(blockId), [])
  const blocks = useMemo(
    () =>
      shown?.scores.features.map((f) => ({
        block_id: f.properties.block_id,
        block_name: f.properties.block_name,
      })) ?? [],
    [shown],
  )
  const onClick = useCallback((info: PickingInfo) => {
    const block = pickedBlock(info)
    setSelectedId(block?.properties.block_id ?? null)
    return block !== null
  }, [])
  const tooltip = useCallback((info: PickingInfo): TooltipContent => {
    if (pickedUnscored(info)) return { text: 'Municipal area, not scored', style: TOOLTIP_STYLE }
    const block = pickedBlock(info)
    if (!block) return null
    const p = block.properties
    const lines = [`${p.block_name}: risk ${p.score.toFixed(2)}`]
    if (p.top_driver) lines.push(`Main driver: ${DRIVER_LABEL[p.top_driver]}`)
    lines.push('Click for the breakdown')
    return { text: lines.join('\n'), style: TOOLTIP_STYLE }
  }, [])

  return {
    view,
    layers,
    highlightLayers,
    tooltip,
    onClick,
    clear,
    select,
    blocks,
    onMapLoad: setMap,
    panel: { visible, state },
    card: { timestepIndex, selected, breakdown, horizon, onClose: clear },
    surge: { total: shown?.breakdown?.surge_population_total ?? null, horizon },
  }
}
