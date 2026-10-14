import { useTimeline } from '../../lib/timeline'
import type { Departure } from '../../types/contracts'
import { formatDuration } from '../impact/labels'
import { DEPARTURE_NOTE } from './wording'

/**
 * "Leave by T-6 → Basanti Rural Hospital, ~37 min by road and ferry (normal conditions)" and the
 * hours left at this timestep; after the deadline, "Road route closed; boat only".
 */
export default function DepartureLine({
  departure: d,
  timestepIndex,
  compact = false,
}: {
  departure: Departure
  timestepIndex: number
  compact?: boolean
}) {
  const timeline = useTimeline()
  const deadline = timeline.indexOf(d.deadline)
  if (deadline < 0 || !d.destination_name || d.travel_time_s == null) {
    return <p className="text-[11px] text-slate-500">{d.note ?? 'No road route to a safe hospital'}</p>
  }
  if (timestepIndex > deadline) {
    return <p className="text-[11px] font-medium text-sev-cut">Road route closed; boat only</p>
  }
  const by = d.uses_ferry ? 'by road and ferry' : 'by road'
  const left = timeline.hoursToLandfall(timestepIndex) - timeline.hoursToLandfall(deadline)
  return (
    <div className="text-[11px]" title={DEPARTURE_NOTE}>
      <p>
        Leave by <span className="font-medium">{timeline.label(deadline)}</span> →{' '}
        {d.destination_name}, ~{formatDuration(d.travel_time_s)} {by} (normal conditions)
        {d.at_risk ? ' · route at risk' : ''}
      </p>
      <p className="font-medium text-sev-act-ink">
        {left === 0 ? 'Last step to leave by road' : `~${left} h left to leave`}
      </p>
      {!compact && <p className="text-ink-subtle">{DEPARTURE_NOTE}</p>}
    </div>
  )
}
