import type { Timeline } from '../../lib/timeline'
import type { AdvisoryStatus, Timestep } from '../../types/contracts'

export const STATUS_STYLE: Record<AdvisoryStatus, string> = {
  draft: 'bg-amber-100 text-amber-800',
  approved: 'bg-emerald-100 text-emerald-800',
  sent: 'bg-sky-100 text-sky-800',
  rejected: 'bg-slate-200 text-slate-600',
}

/** "T-3" for a replay timestep. */
export function timestepLabel(timeline: Timeline, timestep: Timestep): string {
  const i = timeline.indexOf(timestep)
  return i < 0 ? timestep : timeline.label(i)
}
