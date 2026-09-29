import { useState } from 'react'

import { REPLAY_TIMESTEPS, relativeLabel } from '../../lib/constants'
import type { CountdownFacility } from '../../types/contracts'
import { DEPARTURE_NOTE, DepartureLine, type DepartureLookup } from '../departures'
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
  if (i < 0) return 'cut off'
  // Shelter stand-ins have no departure (hospitals and health centres only): just when.
  const at = relativeLabel(i)
  return f.infra_type === 'shelter' ? `cut off from ${at}` : `cut off since ${at}`
}

function FacilityList({
  title,
  items,
  detail,
  departures,
  timestepIndex,
}: {
  title: string
  items: CountdownFacility[]
  detail: (f: CountdownFacility) => string
  departures: DepartureLookup
  timestepIndex: number
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
            {departures.has(f.infra_id) && (
              <div className="ml-2">
                <DepartureLine
                  departure={departures.get(f.infra_id)!}
                  timestepIndex={timestepIndex}
                  compact
                />
              </div>
            )}
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
export default function CountdownPanel({
  state,
  departures,
  timestepIndex,
}: {
  state: CountdownState
  departures: DepartureLookup
  timestepIndex: number
}) {
  return (
    <section className="mt-4">
      <h3 className={HEADING}>Action countdown</h3>
      <p className="mt-1 text-[11px] text-slate-500">{FORECAST_FRAMING}</p>
      <p className="text-[11px] text-slate-500">
        Leave-by times: {DEPARTURE_NOTE.charAt(0).toLowerCase() + DEPARTURE_NOTE.slice(1)}
      </p>
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
            departures={departures}
            timestepIndex={timestepIndex}
          />
          <FacilityList
            key={`c|${state.data.timestep}`}
            title="Already cut off"
            items={state.data.cut_off}
            detail={since}
            departures={departures}
            timestepIndex={timestepIndex}
          />
        </>
      )}
    </section>
  )
}
