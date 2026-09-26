import { useEffect, useState } from 'react'

import { getDispatchReceipts, getDispatchRecipients } from '../../lib/api'
import type { DispatchReceipt, DispatchRecipients } from '../../types/contracts'

export type Loadable<T> =
  | { status: 'loading' }
  | { status: 'ok'; data: T }
  | { status: 'error'; message: string }

const message = (err: unknown) => (err instanceof Error ? err.message : String(err))

/** Who a dispatch would reach (from api/.env), masked. */
export function useRecipients(): Loadable<DispatchRecipients> {
  const [state, setState] = useState<Loadable<DispatchRecipients>>({ status: 'loading' })
  useEffect(() => {
    let cancelled = false
    getDispatchRecipients().then(
      (data) => !cancelled && setState({ status: 'ok', data }),
      (err: unknown) => !cancelled && setState({ status: 'error', message: message(err) }),
    )
    return () => {
      cancelled = true
    }
  }, [])
  return state
}

/** Stored live receipts for an advisory, oldest first; refetched when `version` changes. */
export function useReceipts(advisoryId: string, version: string): Loadable<DispatchReceipt[]> {
  const [state, setState] = useState<{ key: string; value: Loadable<DispatchReceipt[]> }>()
  const key = `${advisoryId}|${version}`
  useEffect(() => {
    let cancelled = false
    getDispatchReceipts(advisoryId).then(
      (data) => !cancelled && setState({ key, value: { status: 'ok', data: data.receipts } }),
      (err: unknown) =>
        !cancelled && setState({ key, value: { status: 'error', message: message(err) } }),
    )
    return () => {
      cancelled = true
    }
  }, [advisoryId, key])
  return state?.key === key ? state.value : { status: 'loading' }
}
