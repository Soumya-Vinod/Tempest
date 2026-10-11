// Exposure feature (Dev B): OSM infrastructure on the map and in the side panel.
import type { Layer } from '@deck.gl/core'
import { useCallback, useMemo, useState } from 'react'

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
  /** Show every health facility and shelter, not only those in the affected area. */
  showAllFacilities: boolean
  toggleShowAllFacilities: () => void
}

/** Infra data and per-type visibility. Layers come from useInfraLayers. */
export function useInfraMap(): InfraMap {
  const state = useInfra()
  const [visible, setVisible] = useState(ALL_VISIBLE)
  const [showAllFacilities, setShowAll] = useState(false)
  const toggle = useCallback(
    (infraType: InfraType) => setVisible((v) => ({ ...v, [infraType]: !v[infraType] })),
    [],
  )
  const toggleShowAllFacilities = useCallback(() => setShowAll((v) => !v), [])
  return { state, visible, toggle, showAllFacilities, toggleShowAllFacilities }
}

/**
 * The deck.gl layers for MapView's overlay. `muted` (impact results showing) switches exposure to
 * greys and pale tints so red and orange mean impact only. `facilities` limits the health
 * facility and shelter points (unless the user shows them all).
 */
export function useInfraLayers(infra: InfraMap, muted: boolean, facilities: FacilityFilter): Layer[] {
  const { state, visible, showAllFacilities } = infra
  const filter = showAllFacilities ? null : facilities
  return useMemo(
    () => buildInfraLayers(state, visible, muted, filter),
    [state, visible, muted, filter],
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
