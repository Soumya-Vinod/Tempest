// Exposure feature (Dev B): OSM infrastructure on the map and in the side panel.
import type { Layer } from '@deck.gl/core'
import { useCallback, useMemo, useState } from 'react'

import type { InfraType } from '../../types/contracts'
import { buildInfraLayers } from './layers'
import { INFRA_TYPES } from './style'
import { useInfra, type InfraByType } from './useInfra'

export { default as InfraPanel } from './InfraPanel'
export { infraTooltip } from './tooltip'

const ALL_VISIBLE = Object.fromEntries(INFRA_TYPES.map((t) => [t, true])) as Record<
  InfraType,
  boolean
>

export interface InfraMap {
  layers: Layer[]
  state: InfraByType
  visible: Record<InfraType, boolean>
  toggle: (infraType: InfraType) => void
}

/** Infra data, per-type visibility and the deck.gl layers for MapView's overlay. */
export function useInfraMap(): InfraMap {
  const state = useInfra()
  const [visible, setVisible] = useState(ALL_VISIBLE)
  const toggle = useCallback(
    (infraType: InfraType) => setVisible((v) => ({ ...v, [infraType]: !v[infraType] })),
    [],
  )
  const layers = useMemo(() => buildInfraLayers(state, visible), [state, visible])
  return { layers, state, visible, toggle }
}
