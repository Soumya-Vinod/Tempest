// Risk feature (Dev B): the "Risk by block" choropleth, unscored areas, block card and panel.
import type { DeckProps, Layer, PickingInfo } from '@deck.gl/core'
import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { REPLAY_TIMESTEPS } from '../../lib/constants'
import { syncUnscored } from './hatch'
import { buildRiskLayers, pickedBlock, pickedUnscored } from './layers'
import type { RiskCardProps } from './RiskCard'
import { DRIVER_LABEL } from './style'
import { type RiskState, useRisk, useUnscoredAreas } from './useRisk'

export { default as RiskCard } from './RiskCard'
export { default as RiskPanel } from './RiskPanel'

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
  layers: Layer[]
  tooltip: (info: PickingInfo) => TooltipContent
  /** Selects the clicked block (true) or clears the selection (false). */
  onClick: (info: PickingInfo) => boolean
  clear: () => void
  onMapLoad: (map: MapLibreMap) => void
  panel: { visible: boolean; onToggle: () => void; state: RiskState }
  card: RiskCardProps
}

/** Risk for the scrubber's timestep; `synthetic` follows the impact toggle. */
export function useRiskMap(timestepIndex: number, synthetic: boolean): RiskMap {
  const timestep = REPLAY_TIMESTEPS[timestepIndex]
  const { state, shown } = useRisk(timestep, synthetic)
  const unscored = useUnscoredAreas()
  const [visible, setVisible] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [map, setMap] = useState<MapLibreMap | null>(null)

  const selected = useMemo(
    () => shown?.scores.features.find((f) => f.properties.block_id === selectedId) ?? null,
    [shown, selectedId],
  )
  const breakdown = useMemo(
    () => shown?.breakdown?.blocks.find((b) => b.block_id === selectedId) ?? null,
    [shown, selectedId],
  )

  const layers = useMemo(
    () => buildRiskLayers(shown?.scores ?? null, unscored, selected, visible),
    [shown, unscored, selected, visible],
  )

  // Hatched unscored areas live in MapLibre (fill-pattern); keep them in sync with the toggle.
  useEffect(() => {
    if (map && unscored) syncUnscored(map, unscored, visible)
  }, [map, unscored, visible])

  const clear = useCallback(() => setSelectedId(null), [])
  const onClick = useCallback((info: PickingInfo) => {
    const block = pickedBlock(info)
    setSelectedId(block?.properties.block_id ?? null)
    return block !== null
  }, [])
  const onToggle = useCallback(() => {
    setVisible((v) => !v)
    setSelectedId(null)
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
    layers,
    tooltip,
    onClick,
    clear,
    onMapLoad: setMap,
    panel: { visible, onToggle, state },
    card: { timestepIndex, selected, breakdown, onClose: clear },
  }
}
