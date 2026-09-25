import type { RiskState } from './useRisk'
import { HATCH, RAMP_CSS } from './style'

interface Props {
  visible: boolean
  onToggle: () => void
  state: RiskState
}

const HATCH_CSS = `repeating-linear-gradient(-45deg, ${HATCH.line} 0 1.5px, transparent 1.5px 5px)`

/** "Risk by block" side-panel section: toggle, fixed-scale legend, status. */
export default function RiskPanel({ visible, onToggle, state }: Props) {
  return (
    <section className="mt-5">
      <label className="mb-2 flex cursor-pointer items-center gap-2">
        <input
          type="checkbox"
          checked={visible}
          onChange={onToggle}
          className="accent-violet-700"
        />
        <span className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
          Risk by block
        </span>
      </label>
      {visible && (
        <>
          <div className="h-2.5 w-full rounded" style={{ background: RAMP_CSS }} aria-hidden />
          <div className="mt-0.5 flex text-[11px] text-slate-500 tabular-nums">
            <span>0</span>
            <span className="ml-auto">0.5</span>
            <span className="ml-auto">1</span>
          </div>
          <p className="text-[11px] text-slate-500">Fixed scale, comparable across timesteps.</p>
          <p className="mt-1 flex items-center gap-2 text-xs text-slate-600">
            <span
              className="size-3 rounded-sm border border-slate-400"
              style={{ background: HATCH_CSS }}
              aria-hidden
            />
            Municipal area, not scored
          </p>
          {state.status === 'loading' && <p className="mt-1 text-xs text-slate-500">Loading…</p>}
          {state.status === 'unavailable' && (
            <p className="mt-1 text-slate-500">Hazard data not available yet</p>
          )}
          {state.status === 'error' && (
            <p className="mt-1 text-xs text-red-600">{state.message}</p>
          )}
          {state.status === 'ok' && (
            <p className="mt-1 text-xs text-slate-500">Click a block for its breakdown.</p>
          )}
        </>
      )}
    </section>
  )
}
