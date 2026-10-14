// Exposure feature (Dev B): OSM infrastructure on the map and in the side panel.
import type { Layer } from '@deck.gl/core'
import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useMemo, useState } from 'react'

import { useDeck } from '../../lib/deck'
import { useZoom } from '../../lib/useZoom'
import type { InfraType } from '../../types/contracts'
import { type BlockArea, type BlockOf, createBlockOf } from './blocks'
import { buildInfraLayers, type FacilityFilter } from './layers'
import { INFRA_TYPES } from './style'
import { useInfra, type InfraByType } from './useInfra'

export { default as InfraPanel } from './InfraPanel'
export type { BlockArea, BlockOf } from './blocks'
export type { FacilityFilter } from './layers'
export { displayName, makeInfraTooltip } from './tooltip'
export type { InfraByType } from './useInfra'

const ALL_VISIBLE = Object.fromEntries(INFRA_TYPES.map((t) => [t, true])) as Record<
  InfraType,
  boolean
>

export interface InfraMap {
  state: InfraByType
  visible: Record<InfraType, boolean>
  toggle: (infraType: InfraType) => void
  /** Highlight every health facility and shelter, not only those in the affected area. */
  highlightAllFacilities: boolean
  toggleHighlightAllFacilities: () => void
}

/** Infra data and per-type visibility. Layers come from useInfraLayers. */
export function useInfraMap(): InfraMap {
  const state = useInfra()
  const [visible, setVisible] = useState(ALL_VISIBLE)
  const [highlightAllFacilities, setHighlightAll] = useState(false)
  const toggle = useCallback(
    (infraType: InfraType) => setVisible((v) => ({ ...v, [infraType]: !v[infraType] })),
    [],
  )
  const toggleHighlightAllFacilities = useCallback(() => setHighlightAll((v) => !v), [])
  return { state, visible, toggle, highlightAllFacilities, toggleHighlightAllFacilities }
}

/**
 * The deck.gl layers for MapView's overlay. `muted` (impact results showing) switches exposure to
 * greys and pale tints so red and orange mean impact only. `facilities` picks the health
 * facilities and shelters drawn in full; the rest are faint (unless the user highlights all).
 */
export function useInfraLayers(
  infra: InfraMap,
  muted: boolean,
  facilities: FacilityFilter,
  map: MapLibreMap | null = null,
): Layer[] {
  const { state, visible, highlightAllFacilities } = infra
  const filter = highlightAllFacilities ? null : facilities
  const deck = useDeck()
  // Road detail and widths follow the zoom (half steps: re-rendered only when one is crossed).
  const zoom = useZoom(map)
  return useMemo(
    () => (deck ? buildInfraLayers(deck, state, visible, muted, filter, zoom) : []),
    [deck, state, visible, muted, filter, zoom],
  )
}

/**
 * A block lookup for labelling unnamed features, rebuilt only when the set of blocks changes
 * (the risk scores are refetched per timestep, with the same polygons).
 */
export function useBlockOf(areas: BlockArea[] | null): BlockOf | null {
  const key = areas?.map((a) => a.name).join('|') ?? ''
  const [built, setBuilt] = useState<{ key: string; blockOf: BlockOf | null }>({
    key: '',
    blockOf: null,
  })
  if (built.key !== key) {
    const next = { key, blockOf: areas && areas.length > 0 ? createBlockOf(areas) : null }
    setBuilt(next)
    return next.blockOf
  }
  return built.blockOf
}
