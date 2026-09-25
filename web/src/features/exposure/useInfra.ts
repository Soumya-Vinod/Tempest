import { useEffect, useState } from 'react'

import { getInfra } from '../../lib/api'
import type { InfraFeatureCollection, InfraType } from '../../types/contracts'
import { INFRA_TYPES } from './style'

export type InfraState =
  | { status: 'loading' }
  | { status: 'ok'; data: InfraFeatureCollection }
  | { status: 'error'; message: string }

export type InfraByType = Record<InfraType, InfraState>

const LOADING = Object.fromEntries(
  INFRA_TYPES.map((t) => [t, { status: 'loading' }]),
) as InfraByType

/**
 * Fetches each infra type separately (GET /api/exposure/infra?infra_type=…), so small layers
 * appear before the roads finish. Each type's `data` object keeps its identity once loaded,
 * which lets deck.gl skip reprocessing layers whose data didn't change.
 */
export function useInfra(): InfraByType {
  const [state, setState] = useState<InfraByType>(LOADING)

  useEffect(() => {
    let cancelled = false
    for (const infraType of INFRA_TYPES) {
      getInfra(infraType).then(
        (data) => {
          if (!cancelled) setState((s) => ({ ...s, [infraType]: { status: 'ok', data } }))
        },
        (err: unknown) => {
          if (!cancelled) {
            const message = err instanceof Error ? err.message : String(err)
            setState((s) => ({ ...s, [infraType]: { status: 'error', message } }))
          }
        },
      )
    }
    return () => {
      cancelled = true
    }
  }, [])

  return state
}
