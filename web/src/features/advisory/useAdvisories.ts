import { useCallback, useEffect, useState } from 'react'

import { getAdvisoryAudit, getAdvisorySuggestions, listAdvisories } from '../../lib/api'
import type { Advisory, AdvisorySuggestions, AuditEvent, Timestep } from '../../types/contracts'

export type Loadable<T> =
  | { status: 'loading' }
  | { status: 'ok'; data: T }
  | { status: 'error'; message: string }

const message = (err: unknown) => (err instanceof Error ? err.message : String(err))

/** Every advisory (newest first), reloaded on demand after an action. */
export function useQueue(): { queue: Loadable<Advisory[]>; reload: () => void } {
  const [queue, setQueue] = useState<Loadable<Advisory[]>>({ status: 'loading' })
  const [version, setVersion] = useState(0)
  useEffect(() => {
    let cancelled = false
    listAdvisories().then(
      (fc) => !cancelled && setQueue({ status: 'ok', data: fc.features }),
      (err: unknown) => !cancelled && setQueue({ status: 'error', message: message(err) }),
    )
    return () => {
      cancelled = true
    }
  }, [version])
  const reload = useCallback(() => setVersion((v) => v + 1), [])
  return { queue, reload }
}

/** Blocks suggested for an advisory at this timestep (risk score at or above the threshold). */
export function useSuggestions(timestep: Timestep): Loadable<AdvisorySuggestions> {
  const [state, setState] = useState<{ key: Timestep; value: Loadable<AdvisorySuggestions> }>()
  useEffect(() => {
    let cancelled = false
    getAdvisorySuggestions(timestep).then(
      (data) => !cancelled && setState({ key: timestep, value: { status: 'ok', data } }),
      (err: unknown) =>
        !cancelled &&
        setState({ key: timestep, value: { status: 'error', message: message(err) } }),
    )
    return () => {
      cancelled = true
    }
  }, [timestep])
  return state?.key === timestep ? state.value : { status: 'loading' }
}

/** The advisory's audit trail; `version` changes whenever the advisory does. */
export function useAudit(advisoryId: string | null, version: string): AuditEvent[] {
  const [events, setEvents] = useState<{ key: string; events: AuditEvent[] }>()
  const key = `${advisoryId}|${version}`
  useEffect(() => {
    if (!advisoryId) return
    let cancelled = false
    getAdvisoryAudit(advisoryId).then(
      (log) => !cancelled && setEvents({ key, events: log.events }),
      () => !cancelled && setEvents({ key, events: [] }),
    )
    return () => {
      cancelled = true
    }
  }, [advisoryId, key])
  return events?.key === key ? events.events : []
}

// --- Approver, remembered in this browser only ---------------------------------------------

export const DESIGNATIONS = [
  'BDO',
  'SDO',
  'ADM (Disaster Management)',
  'District Magistrate',
  'Other',
] as const
export type Designation = (typeof DESIGNATIONS)[number]
export interface Approver {
  name: string
  designation: Designation
  role: string // for "Other"
}

const APPROVER_KEY = 'tempest.advisory.approver'

export function loadApprover(): Approver {
  try {
    const raw = localStorage.getItem(APPROVER_KEY)
    if (raw) {
      const a = JSON.parse(raw) as Partial<Approver>
      if (a.designation && DESIGNATIONS.includes(a.designation)) {
        return { name: a.name ?? '', designation: a.designation, role: a.role ?? '' }
      }
    }
  } catch {
    // Storage unavailable or corrupt: start empty.
  }
  return { name: '', designation: 'BDO', role: '' }
}

export function saveApprover(a: Approver): void {
  try {
    localStorage.setItem(APPROVER_KEY, JSON.stringify(a))
  } catch {
    // Not remembered; nothing else depends on it.
  }
}

/** "Name (Designation)" as the API requires, or "Name (Other: role)". */
export function approverLabel(a: Approver): string {
  const designation = a.designation === 'Other' ? `Other: ${a.role.trim()}` : a.designation
  return `${a.name.trim()} (${designation})`
}
