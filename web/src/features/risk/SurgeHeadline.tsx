import { formatPeople } from '../../lib/format'
import type { Horizon } from '../../types/contracts'
import { SURGE_ESTIMATE_NOTE, surgeWhen } from './surge'

export interface SurgeHeadlineProps {
  /** District total from the risk breakdown; null while it loads or if it is unavailable. */
  total: number | null
  horizon: Horizon
}

/** District headline: "~X people in areas with ≥ 0.3 m surge", always visible in the panel. */
export default function SurgeHeadline({ total, horizon }: SurgeHeadlineProps) {
  if (total === null) return null
  return (
    <section className="mt-4">
      <p className="text-sm">
        <span className="font-semibold tabular-nums">{formatPeople(total)}</span> people in areas
        with ≥ 0.3 m surge{' '}
        <span className="text-xs text-slate-500">({surgeWhen(horizon)})</span>
      </p>
      <p className="text-[11px] text-slate-500">{SURGE_ESTIMATE_NOTE}</p>
    </section>
  )
}
