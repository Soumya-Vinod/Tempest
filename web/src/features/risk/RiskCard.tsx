import { relativeLabel } from '../../lib/constants'
import { CARD_BOTTOM, CARD_TOP_CLEARANCE, PANEL_WIDTH, UI_GAP } from '../../lib/layout'
import { formatPeople } from '../../lib/format'
import type { Horizon, RiskBlockBreakdown, RiskReach, RiskScore } from '../../types/contracts'
import { cssColor, DRIVER_LABEL, PART_LABEL, riskColor } from './style'
import { SURGE_ESTIMATE_NOTE, surgeWhen } from './surge'

/** Below this score a block's "main driver" is noise: the card says so instead. */
const SIGNIFICANT_SCORE = 0.05

export interface RiskCardProps {
  timestepIndex: number
  selected: RiskScore | null
  breakdown: RiskBlockBreakdown | null
  horizon: Horizon
  onClose: () => void
}

function Bar({ label, value, strong }: { label: string; value: number; strong?: boolean }) {
  return (
    <div className={strong ? 'mt-2' : 'mt-0.5 ml-3'}>
      <div className={`flex text-xs ${strong ? 'font-semibold' : 'text-slate-600'}`}>
        <span>{label}</span>
        <span className="ml-auto tabular-nums">{value.toFixed(2)}</span>
      </div>
      <div className={`${strong ? 'h-2' : 'h-1'} w-full rounded-full bg-slate-100`}>
        <div
          className={`h-full rounded-full ${strong ? 'bg-violet-600' : 'bg-violet-300'}`}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
    </div>
  )
}

function Parts({ parts, skip = [] }: { parts: object; skip?: string[] }) {
  return (
    <>
      {Object.entries(parts)
        .filter(([k]) => !skip.includes(k))
        .map(([k, v]) => (
          <Bar key={k} label={PART_LABEL[k] ?? k} value={v as number} />
        ))}
    </>
  )
}

// Which factor scaled the score: hazard on the block's land, or exposure (cut off by the storm).
const REACH_LABEL: Record<RiskReach, string> = {
  direct: 'Direct hazard',
  cut_off: 'Cut off by the storm',
}

function travel(minutes: number | null): string {
  if (minutes === null) return 'No road route'
  if (minutes < 60) return `${Math.round(minutes)} min`
  const m = Math.round(minutes)
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`
}

/** Floating card for the selected block, in the pathway card's slot (bottom-left). */
export default function RiskCard({
  timestepIndex,
  selected,
  breakdown,
  horizon,
  onClose,
}: RiskCardProps) {
  if (!selected) return null
  const p = selected.properties
  const bd = breakdown
  return (
    <aside
      className="absolute z-20 overflow-y-auto rounded-lg bg-white p-3 text-sm text-slate-800 shadow-lg"
      style={{
        left: UI_GAP,
        bottom: CARD_BOTTOM,
        width: PANEL_WIDTH,
        maxHeight: `calc(100% - ${CARD_BOTTOM + CARD_TOP_CLEARANCE}px)`,
      }}
      aria-label="Block risk"
    >
      <div className="flex items-start gap-2">
        <div>
          <p className="font-medium">{p.block_name}</p>
          <p className="text-xs text-slate-500">CD block · {relativeLabel(timestepIndex)}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="-mt-1 ml-auto px-1 text-lg leading-none text-slate-400 hover:text-slate-700"
          aria-label="Close block risk"
        >
          ×
        </button>
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span
          className="size-4 rounded border border-slate-300"
          style={{ background: cssColor(riskColor(p.score)) }}
          aria-hidden
        />
        <span className="text-2xl font-semibold tabular-nums">{p.score.toFixed(2)}</span>
        <span className="text-xs text-slate-500">risk score (0–1)</span>
      </div>
      {p.score < SIGNIFICANT_SCORE ? (
        <p className="mt-1 text-xs text-slate-500">No significant risk</p>
      ) : (
        p.top_driver && (
          <p className="mt-1 text-xs">
            Main driver: <span className="font-medium">{DRIVER_LABEL[p.top_driver]}</span>
          </p>
        )
      )}
      {bd && p.score > 0 && (
        <p className="mt-0.5 text-xs">
          Reached by: <span className="font-medium">{REACH_LABEL[bd.reach]}</span>
        </p>
      )}

      <Bar label="Hazard" value={p.components.hazard} strong />
      {bd && <Parts parts={bd.hazard} />}
      <Bar label="Exposure" value={p.components.exposure} strong />
      {bd && <Parts parts={bd.exposure} />}
      <Bar label="Vulnerability" value={p.components.vulnerability} strong />
      {bd && <Parts parts={bd.vulnerability} skip={['low_literacy']} />}
      {bd && (
        <p className="mt-0.5 ml-3 text-[11px] text-slate-400">
          Low literacy: not used (no primary source yet)
        </p>
      )}

      {bd ? (
        <dl className="mt-3 space-y-0.5 border-t border-slate-100 pt-2 text-xs">
          <div className="flex">
            <dt className="text-slate-500">Population (2011)</dt>
            <dd className="ml-auto tabular-nums">{bd.population_2011.toLocaleString()}</dd>
          </div>
          <div className="flex">
            <dt className="text-slate-500">
              People in areas with ≥ 0.3 m surge ({surgeWhen(horizon)})
            </dt>
            <dd className="ml-auto tabular-nums">{formatPeople(bd.surge_population)}</dd>
          </div>
          <p className="text-[11px] text-slate-400">{SURGE_ESTIMATE_NOTE}</p>
          <div className="flex">
            <dt className="text-slate-500">Median travel time to a hospital (residents)</dt>
            <dd className="ml-auto">{travel(bd.hospital_travel_min)}</dd>
          </div>
        </dl>
      ) : (
        <p className="mt-2 text-xs text-slate-500">Breakdown not available.</p>
      )}
    </aside>
  )
}
