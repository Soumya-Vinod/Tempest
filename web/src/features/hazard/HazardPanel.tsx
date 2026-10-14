import About from '../../components/About'
import { HEADING, SECTION } from '../../lib/panel'
import type { CycloneTrackPoint, HazardLayer, Horizon } from '../../types/contracts'
import { ISOTACH_LEVELS } from './contours'
import {
  FLOOD_RAMP_CSS,
  imdCategory,
  isotachCss,
  isotachWidth,
  SURGE_RAMP_CSS,
  SURGE_TICKS_M,
  toKmh,
} from './style'
import type { HazardState, MapViewMode } from './useHazard'

export interface HazardPanelProps {
  view: MapViewMode
  onView: (view: MapViewMode) => void
  horizon: Horizon
  onHorizon: (horizon: Horizon) => void
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


function Status({ state }: { state: HazardState<unknown> }) {
  if (state.status === 'loading') return <p className="mt-1 text-xs text-slate-500">Loading…</p>
  if (state.status === 'unavailable')
    return <p className="mt-1 text-xs text-slate-500">Not available yet</p>
  if (state.status === 'error') return <p className="mt-1 text-xs text-sev-cut">{state.message}</p>
  return null
}

function Toggle(props: { label: string; on: boolean; onToggle: () => void }) {
  return (
    <label className="mt-3 flex cursor-pointer items-center gap-2 text-xs text-slate-700">
      <input type="checkbox" checked={props.on} onChange={props.onToggle} className="accent-accent" />
      {props.label}
    </label>
  )
}

/** One labelled row; rows stack, so the options never wrap in the 320 px panel. */
function Segmented<T extends string | number>(props: {
  label: string
  caption: string
  value: T
  options: [T, string][]
  onChange: (value: T) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-10 shrink-0 text-[11px] text-slate-500" aria-hidden>
        {props.caption}
      </span>
      <div className="flex flex-1 gap-1 rounded-md bg-slate-100 p-0.5" role="group" aria-label={props.label}>
        {props.options.map(([v, text]) => (
          <button
            key={String(v)}
            type="button"
            aria-pressed={props.value === v}
            onClick={() => props.onChange(v)}
            className={`flex-1 rounded px-2 py-1 text-xs font-medium whitespace-nowrap ${
              props.value === v
                ? 'bg-white text-accent shadow-sm'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  )
}

function Storm({ storm }: { storm: HazardPanelProps['storm'] }) {
  const p = storm.point
  const kmh = p ? toKmh(p.max_wind_mps) : null
  const category = kmh !== null ? imdCategory(kmh) : null
  return (
    <section className={SECTION}>
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
          <dd className="text-ink-muted">{category?.name ?? 'Below depression strength'}</dd>
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
          className="mt-2 rounded-control border border-line px-2.5 py-1 text-xs font-medium text-ink-muted hover:bg-surface"
        >
          {storm.fullTrack ? 'Back to the district' : 'Show full track'}
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
      <section className={SECTION}>
        <h3 className={`${HEADING} mb-2`}>Map view</h3>
        <div className="space-y-1.5">
          <Segmented
            label="Map view"
            caption="Show"
            value={props.view}
            options={[
              ['hazard', 'Hazard'],
              ['risk', 'Risk'],
            ]}
            onChange={props.onView}
          />
          <Segmented<Horizon>
            label="Time"
            caption="When"
            value={props.horizon}
            options={[
              [0, 'Now'],
              [24, 'Next 24 h'],
            ]}
            onChange={props.onHorizon}
          />
        </div>
        <About>
          {props.horizon === 24 && (
            <p>
              Forecast: perfect-forecast replay. The worst over the next 24 h (the replay&apos;s own
              future; operationally, IMD&apos;s forecast track through the same model).
            </p>
          )}
          <p>
            {hazard
              ? 'Hazard: storm surge (and wind, flood if on). Impact and the track show in both.'
              : 'Risk: the block choropleth. Impact and the track show in both.'}
          </p>
        </About>
      </section>

      {hazard && (
        <section className={SECTION}>
          <h3 className={HEADING}>
            Storm surge{props.horizon === 24 && ': max expected in the next 24 h'}
          </h3>
          <div className="mt-2 h-2.5 w-full rounded" style={{ background: SURGE_RAMP_CSS }} aria-hidden />
          <div className="mt-0.5 flex justify-between text-[11px] text-slate-500 tabular-nums">
            {SURGE_TICKS_M.map((m) => (
              <span key={m}>{m} m</span>
            ))}
          </div>
          <p className="text-[11px] text-slate-500">Depth above ground; fixed scale, cells over 0.05 m.</p>
          <Status state={props.surge} />

          <Toggle
            label={
              props.horizon === 24
                ? 'Wind isotachs: max expected in the next 24 h'
                : 'Wind isotachs (IMD categories)'
            }
            on={props.wind.on} onToggle={props.wind.onToggle} />
          {props.wind.on && (
            <>
              <ul className="mt-1 space-y-1 text-[11px] text-slate-600">
                {ISOTACH_LEVELS.map((l, level) => (
                  <li key={l.kmh} className="flex items-center gap-2">
                    <span
                      className="w-6 shrink-0 rounded-full"
                      style={{ height: isotachWidth(level), background: isotachCss(level) }}
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
