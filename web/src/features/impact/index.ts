// Impact feature (Dev B): affected infrastructure on the map, counts and pathways in the panel.
import type { DeckProps, Layer, PickingInfo } from '@deck.gl/core'
import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useMemo, useState } from 'react'

import { useTimeline } from '../../lib/timeline'
import type { Horizon, ImpactStatus } from '../../types/contracts'
import type { BlockOf, InfraByType } from '../exposure'
import type { default as ImpactPanelComponent } from './ImpactPanel'
import type { PathwayCardProps } from './PathwayCard'
import { aggregate, buildImpactLayers, type HaloState, layerData, pickedAffected } from './layers'
import { featureName, infraLookup } from './labels'
import { useAnyInView, usePageVisible, usePulse, useReducedMotion } from './motion'
import { HAZARD_LABEL, PULSE_MS, PULSE_REST_MS, STATUS_LABEL } from './style'
import { useImpacts } from './useImpacts'

export { default as ImpactPanel } from './ImpactPanel'
export { default as PathwayCard } from './PathwayCard'
export { default as StatusSwatch } from './StatusSwatch'

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
  /** The hovered / selected feature's highlight, drawn above everything else. */
  highlightLayers: Layer[]
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
export function useImpactMap(
  timestepIndex: number,
  infra: InfraByType,
  horizon: Horizon = 0,
  blockOf: BlockOf | null = null,
  map: MapLibreMap | null = null,
): ImpactMap {
  const timestep = useTimeline().timesteps[timestepIndex]
  const { state, shown } = useImpacts(timestep, horizon)
  // At horizon 24, what is isolated now (cached, shared with the Now view): the rest of the
  // isolated features are only expected, drawn with a dashed ring.
  const now = useImpacts(timestep, 0)
  const isolatedNow = useMemo(
    () =>
      horizon === 0
        ? null
        : new Set(
            now.shown.filter((r) => r.properties.status === 'isolated').map((r) => r.properties.infra_id),
          ),
    [horizon, now.shown],
  )

  const affected = useMemo(() => aggregate(shown), [shown])
  const data = useMemo(() => layerData(affected, isolatedNow), [affected, isolatedNow])
  const lookup = useMemo(() => infraLookup(infra), [infra])
  // The halo pulses only while isolated facilities are in view on a visible page; static under
  // prefers-reduced-motion. Otherwise nothing animates and the map stays idle.
  const reducedMotion = useReducedMotion()
  const pageVisible = usePageVisible()
  const isolatedPoints = useMemo(
    () => data.isolated.map((a) => a.geometry.coordinates as [number, number]),
    [data.isolated],
  )
  const inView = useAnyInView(map, isolatedPoints)
  const pulse = usePulse(inView && pageVisible && !reducedMotion, PULSE_MS, PULSE_REST_MS)
  const halo: HaloState = reducedMotion ? 'static' : pulse ? 'grow' : 'shrink'

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const highlight = highlightId
    ? (lookup.get(highlightId)?.geometry ?? affected.get(highlightId)?.geometry ?? null)
    : null

  const { layers, highlight: highlightLayers } = useMemo(
    () => buildImpactLayers(data, highlight, halo),
    [data, highlight, halo],
  )

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
      const expected = isolatedNow !== null && a.worst === 'isolated' && !isolatedNow.has(a.id)
      const lines = [
        featureName(a.id, lookup, blockOf),
        ...(expected ? ['Expected to be cut off within 24 h (not yet)'] : []),
        ...a.rows.map(
          (r) => `${HAZARD_LABEL[r.hazard_type]}: ${STATUS_LABEL[r.status].toLowerCase()}`,
        ),
        'Click for the pathway',
      ]
      return { text: lines.join('\n'), style: TOOLTIP_STYLE }
    },
    [lookup, isolatedNow, blockOf],
  )

  const clear = useCallback(() => {
    setSelectedId(null)
    setHighlightId(null)
  }, [])

  return {
    layers,
    highlightLayers,
    active: shown.length > 0,
    tooltip,
    onClick,
    clear,
    panel: {
      timestepIndex,
      horizon,
      expectedCount: data.expected.length,
      state,
      counts,
      affectedCount: state.status === 'ok' ? affected.size : 0,
    },
    card: {
      selectedId,
      selected: selectedId ? (affected.get(selectedId) ?? null) : null,
      lookup,
      blockOf,
      highlightId,
      onHighlight: setHighlightId,
      onClose: clear,
    },
  }
}
