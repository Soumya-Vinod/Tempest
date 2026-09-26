import { relativeLabel } from '../../lib/constants'
import type { ImpactStatus } from '../../types/contracts'
import { cssColor, NON_OK, STATUS_COLOR, STATUS_LABEL } from './style'
import type { ImpactState } from './useImpacts'

interface Props {
  timestepIndex: number
  state: ImpactState
  counts: Record<ImpactStatus, number> | null
  affectedCount: number
}

/** "Impact" side-panel section: counts per status for the scrubber's timestep. */
export default function ImpactPanel(props: Props) {
  const { state, counts } = props
  return (
    <section className="mt-5">
      <h2 className="mb-2 flex items-baseline text-xs font-semibold tracking-wide text-slate-500">
        <span className="uppercase">Impact</span>
        <span className="ml-auto font-normal tracking-normal">
          {relativeLabel(props.timestepIndex)}
        </span>
      </h2>

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
                <span
                  className="size-2.5 shrink-0 rounded-full"
                  style={{ background: cssColor(STATUS_COLOR[s]) }}
                  aria-hidden
                />
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
