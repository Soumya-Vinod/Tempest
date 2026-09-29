import { useState } from 'react'

import { REPLAY_TIMESTEPS, relativeLabel } from '../../lib/constants'
import type { CountdownFacility } from '../../types/contracts'
import { FORECAST_FRAMING } from '../about'
import type { CountdownState } from './useCountdown'

const HEADING = 'text-xs font-semibold tracking-wide text-slate-500 uppercase'
const SHOWN = 6 // per list, before "Show all"

function when(f: CountdownFacility): string {
  if (f.hours_remaining == null) return 'not cut off later in the replay'
  return f.hours_remaining === 0 ? 'now' : `in ~${f.hours_remaining} h`
}

function since(f: CountdownFacility): string {
  const i = f.since ? REPLAY_TIMESTEPS.indexOf(f.since) : -1
  return i >= 0 ? `cut off since ${relativeLabel(i)}` : 'cut off'
}

function FacilityList({
  title,
  items,
  detail,
}: {
  title: string
  items: CountdownFacility[]
  detail: (f: CountdownFacility) => string
}) {
  const [all, setAll] = useState(false)
  if (items.length === 0) return null
  const shown = all ? items : items.slice(0, SHOWN)
  return (
    <div className="mt-2">
      <p className="text-xs font-medium text-slate-700">
        {title} ({items.length})
      </p>
      <ul className="mt-0.5 space-y-0.5 text-xs">
        {shown.map((f) => (
          <li key={f.infra_id} title={f.cut_name ? `First cut: ${f.cut_name}` : undefined}>
            <span className="font-medium">{f.name}</span>
            <span className="text-slate-500"> · {f.cause} · </span>
            <span className="tabular-nums">{detail(f)}</span>
          </li>
        ))}
      </ul>
      {items.length > SHOWN && (
        <button
          type="button"
          onClick={() => setAll((a) => !a)}
          className="mt-0.5 text-xs text-sky-700 hover:underline"
        >
          {all ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      )}
    </div>
  )
}

/**
 * "Action countdown" (v1.3): facilities expected to be cut off within the 24 h forecast window
 * but not yet, soonest first, and those already cut off.
 */
export default function CountdownPanel({ state }: { state: CountdownState }) {
  return (
    <section className="mt-4">
      <h3 className={HEADING}>Action countdown</h3>
      <p className="mt-1 text-[11px] text-slate-500">{FORECAST_FRAMING}</p>
      {state.status === 'loading' && <p className="mt-1 text-xs text-slate-500">Loading…</p>}
      {state.status === 'unavailable' && (
        <p className="mt-1 text-xs text-slate-500">Countdown not available yet</p>
      )}
      {state.status === 'error' && (
        <p className="mt-1 text-xs text-red-600">{state.message}</p>
      )}
      {state.status === 'ok' && (
        <>
          {state.data.expected.length === 0 && state.data.cut_off.length === 0 && (
            <p className="mt-1 text-xs text-slate-600">
              No facility expected to be cut off in the next 24 h.
            </p>
          )}
          <FacilityList
            key={`e|${state.data.timestep}`}
            title="Expected to be cut off"
            items={state.data.expected}
            detail={when}
          />
          <FacilityList
            key={`c|${state.data.timestep}`}
            title="Already cut off"
            items={state.data.cut_off}
            detail={since}
          />
        </>
      )}
    </section>
  )
}
