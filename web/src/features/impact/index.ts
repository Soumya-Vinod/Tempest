// Impact feature (Dev B): affected infrastructure on the map, counts and pathways in the panel.
import type { DeckProps, Layer, PickingInfo } from '@deck.gl/core'
import { useCallback, useMemo, useState } from 'react'

import { REPLAY_TIMESTEPS } from '../../lib/constants'
import type { ImpactStatus } from '../../types/contracts'
import type { InfraByType } from '../exposure'
import type { default as ImpactPanelComponent } from './ImpactPanel'
import type { PathwayCardProps } from './PathwayCard'
import { aggregate, buildImpactLayers, layerData, pickedAffected } from './layers'
import { featureName, infraLookup } from './labels'
import { HAZARD_LABEL, PULSE_MS, STATUS_LABEL } from './style'
import { useImpacts, usePulse } from './useImpacts'

export { default as ImpactPanel } from './ImpactPanel'
export { default as PathwayCard } from './PathwayCard'

type TooltipContent = ReturnType<NonNullable<DeckProps['getTooltip']>>
type PanelProps = Parameters<typeof ImpactPanelComponent>[0]

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

export interface ImpactMap {
  layers: Layer[]
  /** Impact results are on the map (exposure should mute its colours). */
  active: boolean
  /** Tooltip for impact layers; null elsewhere, so the exposure tooltip can take over. */
  tooltip: (info: PickingInfo) => TooltipContent
  /** Selects the clicked affected feature (true) or clears the selection (false). */
  onClick: (info: PickingInfo) => boolean
  clear: () => void
  panel: PanelProps
  card: PathwayCardProps
}

/** Impact results for the scrubber's timestep as map layers, a tooltip, and panel props. */
export function useImpactMap(timestepIndex: number, infra: InfraByType): ImpactMap {
  const timestep = REPLAY_TIMESTEPS[timestepIndex]
  const { state, shown } = useImpacts(timestep)

  const affected = useMemo(() => aggregate(shown), [shown])
  const data = useMemo(() => layerData(affected), [affected])
  const lookup = useMemo(() => infraLookup(infra), [infra])
  const pulse = usePulse(data.isolated.length > 0, PULSE_MS)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const highlight = highlightId
    ? (lookup.get(highlightId)?.geometry ?? affected.get(highlightId)?.geometry ?? null)
    : null

  const layers = useMemo(() => buildImpactLayers(data, highlight, pulse), [data, highlight, pulse])

  const counts = useMemo(() => {
    if (state.status !== 'ok') return null
    const c: Record<ImpactStatus, number> = { ok: 0, at_risk: 0, cut: 0, isolated: 0 }
    for (const r of state.data) c[r.properties.status] += 1
    return c
  }, [state])

  const onClick = useCallback((info: PickingInfo) => {
    const a = pickedAffected(info)
    setSelectedId(a?.id ?? null)
    setHighlightId(a?.id ?? null)
    return a !== null
  }, [])

  const tooltip = useCallback(
    (info: PickingInfo): TooltipContent => {
      const a = pickedAffected(info)
      if (!a) return null
      const lines = [
        featureName(a.id, lookup),
        ...a.rows.map(
          (r) => `${HAZARD_LABEL[r.hazard_type]}: ${STATUS_LABEL[r.status].toLowerCase()}`,
        ),
        'Click for the pathway',
      ]
      return { text: lines.join('\n'), style: TOOLTIP_STYLE }
    },
    [lookup],
  )

  const clear = useCallback(() => {
    setSelectedId(null)
    setHighlightId(null)
  }, [])

  return {
    layers,
    active: shown.length > 0,
    tooltip,
    onClick,
    clear,
    panel: {
      timestepIndex,
      state,
      counts,
      affectedCount: state.status === 'ok' ? affected.size : 0,
    },
    card: {
      selectedId,
      selected: selectedId ? (affected.get(selectedId) ?? null) : null,
      lookup,
      highlightId,
      onHighlight: setHighlightId,
      onClose: clear,
    },
  }
}
