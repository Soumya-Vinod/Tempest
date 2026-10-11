import { useTimeline } from '../../lib/timeline'
import type { Horizon, ImpactStatus } from '../../types/contracts'
import StatusSwatch from './StatusSwatch'
import { NON_OK, STATUS_LABEL } from './style'
import type { ImpactState } from './useImpacts'

interface Props {
  timestepIndex: number
  horizon: Horizon
  expectedCount: number // isolated only on the expected hazard (horizon 24), not now
  state: ImpactState
  counts: Record<ImpactStatus, number> | null
  affectedCount: number
}

/** "Impact" side-panel section: counts per status for the scrubber's timestep. */
export default function ImpactPanel(props: Props) {
  const timeline = useTimeline()
  const { state, counts } = props
  return (
    <section className="mt-5">
      <h2 className="mb-2 flex items-baseline text-xs font-semibold tracking-wide text-slate-500">
        <span className="uppercase">Impact</span>
        <span className="ml-auto font-normal tracking-normal">
          {timeline.label(props.timestepIndex)}
          {props.horizon === 24 && ', next 24 h'}
        </span>
      </h2>
      {props.horizon === 24 && (
        <p className="mb-1 flex items-start gap-1.5 text-[11px] text-slate-500">
          <StatusSwatch status="isolated" expected />
          <span>
            Expected within the next 24 h (worst case). Dashed rings: expected to be cut off, not
            yet ({props.expectedCount}).
          </span>
        </p>
      )}

      {state.status === 'loading' && <p className="text-xs text-slate-500">Loading…</p>}
      {state.status === 'unavailable' && (
        <p className="text-slate-500">Hazard data not available yet</p>
      )}
      {state.status === 'error' && <p className="text-xs text-red-600">{state.message}</p>}
      {state.status === 'ok' && counts && (
        <>
          <ul className="space-y-1">
            {NON_OK.map((s) => (
              <li key={s} className="flex items-center gap-2">
                <StatusSwatch status={s} />
                <span>{STATUS_LABEL[s]}</span>
                <span className="ml-auto text-xs text-slate-500 tabular-nums">
                  {counts[s].toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-slate-500">
            Results (one per feature and hazard) · {props.affectedCount.toLocaleString()} features
            affected. Click one on the map for its pathway.
          </p>
        </>
      )}
    </section>
  )
}
