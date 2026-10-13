import type { Timeline } from '../../lib/timeline'
import type { AdvisoryStatus, Timestep } from '../../types/contracts'

/** A status chip: small, rounded, quiet (no severity colours). */
export const CHIP = 'inline-block rounded-full border px-2 text-[11px] leading-5 whitespace-nowrap'

export const STATUS_STYLE: Record<AdvisoryStatus, string> = {
  draft: 'border-accent/30 bg-accent-wash text-accent',
  approved: 'border-emerald-700/25 bg-emerald-50 text-emerald-800',
  sent: 'border-line bg-surface text-ink-muted',
  rejected: 'border-line bg-white text-ink-subtle',
}
/** A suggested block with no advisory yet. */
export const SUGGESTED_STYLE = 'border-line bg-white text-ink-subtle'

export const STATUS_LABEL: Record<AdvisoryStatus, string> = {
  draft: 'Draft',
  approved: 'Approved',
  sent: 'Sent',
  rejected: 'Rejected',
}

/** Buttons: one primary action per view; the rest secondary or quiet. */
export const BUTTON = {
  primary:
    'rounded-control border border-accent bg-accent px-3 py-1 text-xs font-medium text-white hover:bg-accent-strong disabled:border-slate-300 disabled:bg-slate-300',
  secondary:
    'rounded-control border border-line bg-white px-3 py-1 text-xs font-medium text-ink-muted hover:bg-surface disabled:opacity-50',
  quiet: 'rounded-control px-2 py-1 text-xs text-ink-subtle hover:bg-surface hover:text-ink disabled:opacity-50',
}

/** "T-3" for a replay timestep. */
export function timestepLabel(timeline: Timeline, timestep: Timestep): string {
  const i = timeline.indexOf(timestep)
  return i < 0 ? timestep : timeline.label(i)
}
