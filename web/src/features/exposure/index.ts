// Exposure feature (Dev B): OSM infrastructure on the map and in the side panel.
import type { Layer } from '@deck.gl/core'
import { useCallback, useMemo, useState } from 'react'

import type { InfraType } from '../../types/contracts'
import { buildInfraLayers } from './layers'
import { INFRA_TYPES } from './style'
import { useInfra, type InfraByType } from './useInfra'

export { default as InfraPanel } from './InfraPanel'
export { infraTooltip } from './tooltip'
export type { InfraByType } from './useInfra'

const ALL_VISIBLE = Object.fromEntries(INFRA_TYPES.map((t) => [t, true])) as Record<
  InfraType,
  boolean
>

export interface InfraMap {
  state: InfraByType
  visible: Record<InfraType, boolean>
  toggle: (infraType: InfraType) => void
}

/** Infra data and per-type visibility. Layers come from useInfraLayers. */
export function useInfraMap(): InfraMap {
  const state = useInfra()
  const [visible, setVisible] = useState(ALL_VISIBLE)
  const toggle = useCallback(
    (infraType: InfraType) => setVisible((v) => ({ ...v, [infraType]: !v[infraType] })),
    [],
  )
  return { state, visible, toggle }
}

/**
 * The deck.gl layers for MapView's overlay. `muted` (impact results showing) switches exposure to
 * greys and pale tints so red and orange mean impact only.
 */
export function useInfraLayers(infra: InfraMap, muted: boolean): Layer[] {
  const { state, visible } = infra
  return useMemo(() => buildInfraLayers(state, visible, muted), [state, visible, muted])
}
