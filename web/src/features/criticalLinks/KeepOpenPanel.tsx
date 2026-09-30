import { REPLAY_TIMESTEPS, relativeLabel } from '../../lib/constants'
import type { Horizon, Timestep } from '../../types/contracts'
import { entryOf, type LinkEntry, type LinkGroups, ROADS_SHOWN } from './grouping'
import type { CriticalLinksState } from './useCriticalLinks'

const HEADING = 'text-xs font-semibold tracking-wide text-slate-500 uppercase'

function count(n: number): string {
  return `${n} ${n === 1 ? 'facility' : 'facilities'}`
}

function before(deadline: Timestep): string {
  const i = REPLAY_TIMESTEPS.indexOf(deadline)
  return i >= 0 ? ` · before ${relativeLabel(i)}` : ''
}

interface Highlight {
  pinned: string | null
  onHover: (key: string | null) => void
  onPin: (key: string | null) => void
}

/** "Diamond Harbour Road (Namkhana → Kulpi) · 9 facilities · before T-21", its facilities, and
 *  for a grouped entry, its segments while expanded. */
function Entry({ entry, pinned, onHover, onPin }: { entry: LinkEntry } & Highlight) {
  const grouped = entry.segments.length > 1
  const expanded = grouped && entryOf({ roads: [entry], ferries: [] }, pinned) === entry.key
  const on = pinned === entry.key
  return (
    <li>
      <button
        type="button"
        aria-pressed={on}
        aria-expanded={grouped ? expanded : undefined}
        onMouseEnter={() => onHover(entry.key)}
        onFocus={() => onHover(entry.key)}
        onBlur={() => onHover(null)}
        onClick={() => onPin(expanded || on ? null : entry.key)}
        className={`w-full rounded px-1 py-0.5 text-left hover:bg-amber-50 ${
          on || expanded ? 'bg-amber-100' : ''
        }`}
      >
        <span className="font-medium">{entry.label}</span>
        <span className="tabular-nums">
          {' '}
          · {count(entry.facilities.length)}
          {before(entry.earliest_deadline)}
        </span>
        {grouped && (
          <span className="text-slate-500"> · {expanded ? '▾' : '▸'} {entry.segments.length} segments</span>
        )}
        <span className="block text-[11px] text-slate-500">
          {entry.facilities.map((f) => f.name).join(', ')}
        </span>
      </button>
      {expanded && (
        <ul className="mt-0.5 ml-3 space-y-0.5 border-l border-amber-200 pl-2">
          {entry.segments.map((s) => (
            <li key={s.key}>
              <button
                type="button"
                aria-pressed={pinned === s.key}
                title={s.link.facilities.map((f) => f.name).join(', ')}
                onMouseEnter={() => onHover(s.key)}
                onMouseLeave={() => onHover(entry.key)}
                onFocus={() => onHover(s.key)}
                onBlur={() => onHover(null)}
                onClick={() => onPin(pinned === s.key ? entry.key : s.key)}
                className={`w-full rounded px-1 text-left text-[11px] hover:bg-amber-50 ${
                  pinned === s.key ? 'bg-amber-100 font-medium' : ''
                }`}
              >
                {s.label} · {count(s.link.facility_count)}
                {before(s.link.earliest_deadline)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function EntryList({ title, entries, empty, ...highlight }: {
  title: string
  entries: LinkEntry[]
  empty: string
} & Highlight) {
  return (
    <div className="mt-2">
      <p className="text-xs font-medium text-slate-700">{title}</p>
      {entries.length === 0 ? (
        <p className="text-xs text-slate-500">{empty}</p>
      ) : (
        <ol className="mt-0.5 space-y-0.5 text-xs" onMouseLeave={() => highlight.onHover(null)}>
          {entries.map((e) => (
            <Entry key={e.key} entry={e} {...highlight} />
          ))}
        </ol>
      )}
    </div>
  )
}

/**
 * "Keep these open" (v1.4): the roads (top 5, grouped by name) and every ferry crossing the last
 * safe departure routes still need. Hovering an entry highlights it on the map; clicking keeps
 * it highlighted and, for a grouped entry, lists its segments.
 */
export default function KeepOpenPanel({
  state,
  groups,
  horizon,
  ...highlight
}: {
  state: CriticalLinksState
  groups: LinkGroups | null
  horizon: Horizon
} & Highlight) {
  const scope =
    horizon === 24
      ? 'Routes of facilities whose last road departure is within the next 24 h.'
      : 'Routes of facilities that can still leave by road.'
  return (
    <section className="mt-4">
      <h3 className={HEADING}>Keep these open</h3>
      <p className="mt-1 text-[11px] text-slate-500">{scope}</p>
      {state.status === 'loading' && <p className="mt-1 text-xs text-slate-500">Loading…</p>}
      {state.status === 'unavailable' && (
        <p className="mt-1 text-xs text-slate-500">Critical links not available yet</p>
      )}
      {state.status === 'error' && <p className="mt-1 text-xs text-red-600">{state.message}</p>}
      {state.status === 'ok' && groups && (
        <>
          {state.data.links.length === 0 ? (
            <p className="mt-1 text-xs text-slate-600">No road departures left to protect.</p>
          ) : (
            <>
              <EntryList
                title="Roads to keep clear"
                entries={groups.roads.slice(0, ROADS_SHOWN)}
                empty="No road needed."
                {...highlight}
              />
              <EntryList
                title={`Ferry crossings to keep running (${groups.ferries.length})`}
                entries={groups.ferries}
                empty="No ferry crossing needed."
                {...highlight}
              />
            </>
          )}
          <p className="mt-1 text-[11px] text-slate-500">{state.data.note}</p>
        </>
      )}
    </section>
  )
}
