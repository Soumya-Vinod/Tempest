import type { CycloneTrackPoint, HazardLayer } from '../../types/contracts'
import { ISOTACH_LEVELS } from './contours'
import {
  FLOOD_RAMP_CSS,
  imdCategory,
  ISOTACH_CSS,
  isotachWidth,
  SURGE_RAMP_CSS,
  SURGE_TICKS_M,
  toKmh,
} from './style'
import type { HazardState, MapViewMode } from './useHazard'

export interface HazardPanelProps {
  view: MapViewMode
  onView: (view: MapViewMode) => void
  surge: HazardState<HazardLayer[]>
  wind: { on: boolean; onToggle: () => void; state: HazardState<HazardLayer[]> }
  flood: { on: boolean; onToggle: () => void; state: HazardState<HazardLayer[]> }
  storm: {
    state: HazardState<unknown>
    point: CycloneTrackPoint | null
    hoursToLandfall: number
    fullTrack: boolean
    onFullTrack: () => void
    onBackToAoi: () => void
  }
}

const HEADING = 'text-xs font-semibold tracking-wide text-slate-500 uppercase'

function Status({ state }: { state: HazardState<unknown> }) {
  if (state.status === 'loading') return <p className="mt-1 text-xs text-slate-500">Loading…</p>
  if (state.status === 'unavailable')
    return <p className="mt-1 text-xs text-slate-500">Not available yet</p>
  if (state.status === 'error') return <p className="mt-1 text-xs text-red-600">{state.message}</p>
  return null
}

function Toggle(props: { label: string; on: boolean; onToggle: () => void }) {
  return (
    <label className="mt-3 flex cursor-pointer items-center gap-2 text-xs text-slate-700">
      <input type="checkbox" checked={props.on} onChange={props.onToggle} className="accent-violet-700" />
      {props.label}
    </label>
  )
}

function ViewSwitch({ view, onView }: { view: MapViewMode; onView: (v: MapViewMode) => void }) {
  const option = (v: MapViewMode, label: string) => (
    <button
      type="button"
      aria-pressed={view === v}
      onClick={() => onView(v)}
      className={`flex-1 rounded px-2 py-1 text-xs font-medium ${
        view === v ? 'bg-white text-violet-800 shadow-sm' : 'text-slate-600 hover:text-slate-800'
      }`}
    >
      {label}
    </button>
  )
  return (
    <div className="flex gap-1 rounded-md bg-slate-100 p-0.5" role="group" aria-label="Map view">
      {option('hazard', 'Hazard')}
      {option('risk', 'Risk')}
    </div>
  )
}

function Storm({ storm }: { storm: HazardPanelProps['storm'] }) {
  const p = storm.point
  const kmh = p ? toKmh(p.max_wind_mps) : null
  const category = kmh !== null ? imdCategory(kmh) : null
  return (
    <section className="mt-5">
      <h3 className={HEADING}>Storm</h3>
      <Status state={storm.state} />
      {p && kmh !== null && (
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
          <dt className="text-slate-500">Position</dt>
          <dd className="tabular-nums">
            {p.lat.toFixed(2)}°N, {p.lon.toFixed(2)}°E
          </dd>
          <dt className="text-slate-500">Max wind</dt>
          <dd className="tabular-nums">{Math.round(kmh)} km/h</dd>
          <dt className="text-slate-500">IMD category</dt>
          <dd>{category?.name ?? 'Below depression strength'}</dd>
          <dt className="text-slate-500">Landfall</dt>
          <dd className="tabular-nums">
            {storm.hoursToLandfall > 0 ? `in ${storm.hoursToLandfall} h` : 'now (T-0)'}
          </dd>
        </dl>
      )}
      {p && (
        <button
          type="button"
          onClick={storm.fullTrack ? storm.onBackToAoi : storm.onFullTrack}
          className="mt-2 rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          {storm.fullTrack ? 'Back to AOI' : 'Show full track'}
        </button>
      )}
    </section>
  )
}

/** Map-view switch, hazard legends and toggles, and the Storm section. */
export default function HazardPanel(props: HazardPanelProps) {
  const hazard = props.view === 'hazard'
  return (
    <>
      <section className="mt-5">
        <h3 className={`${HEADING} mb-2`}>Map view</h3>
        <ViewSwitch view={props.view} onView={props.onView} />
        <p className="mt-1 text-[11px] text-slate-500">
          {hazard
            ? 'Hazard: storm surge (and wind, flood if on). Impact and the track show in both.'
            : 'Risk: the block choropleth. Impact and the track show in both.'}
        </p>
      </section>

      {hazard && (
        <section className="mt-4">
          <h3 className={HEADING}>Storm surge</h3>
          <div className="mt-2 h-2.5 w-full rounded" style={{ background: SURGE_RAMP_CSS }} aria-hidden />
          <div className="mt-0.5 flex justify-between text-[11px] text-slate-500 tabular-nums">
            {SURGE_TICKS_M.map((m) => (
              <span key={m}>{m} m</span>
            ))}
          </div>
          <p className="text-[11px] text-slate-500">Depth above ground; fixed scale, cells over 0.05 m.</p>
          <Status state={props.surge} />

          <Toggle label="Wind isotachs (IMD categories)" on={props.wind.on} onToggle={props.wind.onToggle} />
          {props.wind.on && (
            <>
              <ul className="mt-1 space-y-1 text-[11px] text-slate-600">
                {ISOTACH_LEVELS.map((l, level) => (
                  <li key={l.kmh} className="flex items-center gap-2">
                    <span
                      className="w-6 shrink-0 rounded-full"
                      style={{ height: isotachWidth(level), background: ISOTACH_CSS }}
                      aria-hidden
                    />
                    <span className="w-14 shrink-0 tabular-nums">{l.kmh} km/h</span>
                    <span>{l.category}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-[11px] text-slate-500">
                Lines at the category boundaries; hover a line for its category.
              </p>
              <Status state={props.wind.state} />
            </>
          )}

          <Toggle label="Flood susceptibility (static)" on={props.flood.on} onToggle={props.flood.onToggle} />
          {props.flood.on && (
            <>
              <div className="mt-1 h-2 w-full rounded" style={{ background: FLOOD_RAMP_CSS }} aria-hidden />
              <div className="mt-0.5 flex justify-between text-[11px] text-slate-500">
                <span>Low</span>
                <span>High</span>
              </div>
              <Status state={props.flood.state} />
            </>
          )}
        </section>
      )}

      <Storm storm={props.storm} />
    </>
  )
}
