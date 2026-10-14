import { useState } from 'react'

import { type Timeline, useTimeline } from '../../lib/timeline'
import type { CountdownFacility } from '../../types/contracts'
import { DEPARTURE_NOTE, DepartureLine, type DepartureLookup } from '../departures'
import { FORECAST_FRAMING } from '../about'
import About from '../../components/About'
import { HEADING, SECTION, SUBHEADING } from '../../lib/panel'
import { StatusSwatch } from '../impact'
import type { CountdownState } from './useCountdown'

const SHOWN = 6 // per quiet group (Later, Already cut off), before "Show all"

type GroupId = 'soon' | 'within12' | 'later' | 'cutOff'

const GROUPS: { id: GroupId; title: string; collapse: boolean }[] = [
  { id: 'soon', title: 'Leave within 3 h', collapse: false },
  { id: 'within12', title: 'Within 12 h', collapse: false },
  { id: 'later', title: 'Later', collapse: true },
  { id: 'cutOff', title: 'Already cut off', collapse: true },
]

interface Row {
  f: CountdownFacility
  cutOff: boolean
  group: GroupId
  /** The short right-hand label: "leave by T-6", "since T-3", "in ~9 h". */
  when: string
}

/**
 * Hours left to act on an expected facility: until its last road departure if it has one (0 once
 * the deadline has passed: boat only), else until it is expected to be cut off; null if never.
 */
function hoursLeft(f: CountdownFacility, departures: DepartureLookup, i: number, timeline: Timeline) {
  const d = departures.get(f.infra_id)
  const deadline = d ? timeline.indexOf(d.deadline) : -1
  if (deadline >= 0 && d?.destination_name && d.travel_time_s != null) {
    return Math.max(0, timeline.hoursToLandfall(i) - timeline.hoursToLandfall(deadline))
  }
  return f.hours_remaining ?? null
}

function expectedWhen(f: CountdownFacility, departures: DepartureLookup, i: number, timeline: Timeline) {
  const d = departures.get(f.infra_id)
  const deadline = d ? timeline.indexOf(d.deadline) : -1
  if (deadline >= 0 && d?.destination_name && d.travel_time_s != null) {
    return i > deadline ? 'boat only' : `leave by ${timeline.label(deadline)}`
  }
  if (f.hours_remaining == null) return 'not later in the replay'
  return f.hours_remaining === 0 ? 'now' : `in ~${f.hours_remaining} h`
}

function since(f: CountdownFacility, timeline: Timeline): string {
  const i = timeline.indexOf(f.since)
  return i < 0 ? 'cut off' : `since ${timeline.label(i)}`
}

function rows(
  expected: CountdownFacility[],
  cutOff: CountdownFacility[],
  departures: DepartureLookup,
  i: number,
  timeline: Timeline,
): Row[] {
  const ahead = expected
    .map((f) => ({ f, left: hoursLeft(f, departures, i, timeline) }))
    .sort((a, b) => (a.left ?? Infinity) - (b.left ?? Infinity))
    .map(({ f, left }): Row => ({
      f,
      cutOff: false,
      group: left === null ? 'later' : left <= 3 ? 'soon' : left <= 12 ? 'within12' : 'later',
      when: expectedWhen(f, departures, i, timeline),
    }))
  return [...ahead, ...cutOff.map((f): Row => ({ f, cutOff: true, group: 'cutOff', when: since(f, timeline) }))]
}

/** One facility: a one-line button (status · name · cause · when); details when expanded. */
function FacilityRow({
  row,
  open,
  onToggle,
  departures,
  timestepIndex,
  urgent,
}: {
  row: Row
  open: boolean
  onToggle: () => void
  departures: DepartureLookup
  timestepIndex: number
  urgent: boolean
}) {
  const { f, cutOff } = row
  const departure = departures.get(f.infra_id)
  const whenTone = cutOff ? 'text-sev-cut' : urgent ? 'font-medium text-sev-act-ink' : 'text-ink-muted'
  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        title={`${f.name} · ${f.cause}`}
        className={`flex w-full items-center gap-2 rounded-control px-1.5 py-1 text-left text-xs hover:bg-surface ${
          open ? 'bg-surface' : ''
        }`}
      >
        <StatusSwatch status="isolated" expected={!cutOff} />
        <span className="min-w-0 flex-1 truncate">
          <span className="font-medium text-ink">{f.name}</span>
          <span className="text-ink-subtle"> · {f.cause}</span>
        </span>
        <span className={`shrink-0 tabular-nums ${whenTone}`}>{row.when}</span>
      </button>
      {open && (
        <div className="mt-0.5 mb-1.5 ml-7 space-y-0.5 text-[11px] text-ink-muted">
          <p>
            {cutOff ? 'Cut off' : 'Expected to be cut off'}: {f.cause}
            {f.cut_name && <span className="text-ink-subtle"> · first cut: {f.cut_name}</span>}
          </p>
          {departure ? (
            <DepartureLine departure={departure} timestepIndex={timestepIndex} compact />
          ) : (
            <p className="text-ink-subtle">No departure route for this facility.</p>
          )}
        </div>
      )}
    </li>
  )
}

function Group({
  title,
  items,
  collapse,
  openId,
  onToggle,
  departures,
  timestepIndex,
  urgent,
}: {
  title: string
  items: Row[]
  collapse: boolean
  openId: string | null
  onToggle: (id: string) => void
  departures: DepartureLookup
  timestepIndex: number
  urgent: boolean
}) {
  const [all, setAll] = useState(false)
  if (items.length === 0) return null
  const shown = all || !collapse ? items : items.slice(0, SHOWN)
  return (
    <div className="mt-3">
      <p className={`mb-0.5 flex items-baseline gap-1.5 ${SUBHEADING}`}>
        {title}
        <span className="tabular-nums">· {items.length}</span>
      </p>
      <ul>
        {shown.map((r) => (
          <FacilityRow
            key={r.f.infra_id}
            row={r}
            open={openId === r.f.infra_id}
            onToggle={() => onToggle(r.f.infra_id)}
            departures={departures}
            timestepIndex={timestepIndex}
            urgent={urgent}
          />
        ))}
      </ul>
      {collapse && items.length > SHOWN ? (
        <button
          type="button"
          onClick={() => setAll((a) => !a)}
          className="mt-0.5 ml-1.5 text-[11px] text-accent hover:underline"
        >
          {all ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      ) : null}
    </div>
  )
}

/**
 * "Action countdown" (v1.3): facilities expected to be cut off within the 24 h forecast window
 * but not yet, grouped by how soon patients must leave by road, and those already cut off. One
 * line each; a click expands the details (destination, travel time, route) and highlights the
 * facility on the map.
 */
export default function CountdownPanel({
  state,
  departures,
  timestepIndex,
  onHighlight,
}: {
  state: CountdownState
  departures: DepartureLookup
  timestepIndex: number
  /** Highlight a facility on the map (null: none). */
  onHighlight?: (infraId: string | null) => void
}) {
  const timeline = useTimeline()
  const [openId, setOpenId] = useState<string | null>(null)
  const toggle = (id: string) => {
    const next = openId === id ? null : id
    setOpenId(next)
    onHighlight?.(next)
  }
  const all =
    state.status === 'ok'
      ? rows(state.data.expected, state.data.cut_off, departures, timestepIndex, timeline)
      : []
  return (
    <section className={SECTION}>
      <h3 className={HEADING}>Action countdown</h3>
      <About>
        <p>{FORECAST_FRAMING}</p>
        <p>Leave-by times: {DEPARTURE_NOTE.charAt(0).toLowerCase() + DEPARTURE_NOTE.slice(1)}</p>
      </About>
      {state.status === 'loading' && <p className="mt-1 text-xs text-ink-subtle">Loading…</p>}
      {state.status === 'unavailable' && (
        <p className="mt-1 text-xs text-ink-subtle">The countdown is not available yet.</p>
      )}
      {state.status === 'error' && <p className="mt-1 text-xs text-sev-cut">{state.message}</p>}
      {state.status === 'ok' && (
        <>
          {all.length === 0 && (
            <p className="mt-2 text-xs text-ink-muted">
              No facility expected to be cut off in the next 24 h.
            </p>
          )}
          {GROUPS.map((g) => (
            <Group
              key={`${g.id}|${state.data.timestep}`}
              title={g.title}
              items={all.filter((r) => r.group === g.id)}
              collapse={g.collapse}
              openId={openId}
              onToggle={toggle}
              departures={departures}
              timestepIndex={timestepIndex}
              urgent={g.id === 'soon'}
            />
          ))}
        </>
      )}
    </section>
  )
}
