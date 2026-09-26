import { LANDFALL_INDEX, relativeLabel } from '../../lib/constants'
import type { InsuranceSummary, TriggerEvent } from '../../types/contracts'
import { crore, hoursLabel, METRIC_LABEL, readingLabel, TIER_PERCENT } from './format'
import type { Loadable } from './useInsurance'

export interface InsurancePanelProps {
  timestepIndex: number
  triggers: Loadable<TriggerEvent[]>
  shown: TriggerEvent[]
  summary: Loadable<InsuranceSummary>
}

const HEADING = 'text-xs font-semibold tracking-wide text-slate-500 uppercase'

function Status({ state }: { state: Loadable<unknown> }) {
  if (state.status === 'loading') return <p className="mt-1 text-xs text-slate-500">Loading…</p>
  if (state.status === 'unavailable')
    return <p className="mt-1 text-xs text-slate-500">Not available yet</p>
  if (state.status === 'error') return <p className="mt-1 text-xs text-red-600">{state.message}</p>
  return null
}

/**
 * "Insurance (illustrative)": the district total pre-positioned so far (released amounts only
 * go up), each paying block's current reading and what it has released, and first triggers.
 */
export default function InsurancePanel(props: InsurancePanelProps) {
  const paying = props.shown
    .filter((f) => f.properties.released_tier > 0)
    .sort((a, b) => b.properties.released_payout_inr - a.properties.released_payout_inr)
  const released = paying.reduce((sum, f) => sum + f.properties.released_payout_inr, 0)
  // Blocks the expected hazard (next 24 h) would trigger that haven't been paid yet (v1.3).
  const upcoming = props.shown
    .filter((f) => f.properties.released_tier === 0 && (f.properties.expected_tier_24h ?? 0) > 0)
    .sort((a, b) => (b.properties.expected_tier_24h ?? 0) - (a.properties.expected_tier_24h ?? 0))
  const zones = props.summary.status === 'ok' ? props.summary.data.zones : []
  const firstBy = new Map(zones.map((z) => [z.zone_id, z]))
  // Anticipatory headlines: blocks whose first trigger is at or before this timestep.
  const headlines = zones
    .filter(
      (z) =>
        z.first_trigger_timestep !== null &&
        z.hours_before_landfall !== null &&
        z.hours_before_landfall >= (LANDFALL_INDEX - props.timestepIndex) * 3,
    )
    .sort((a, b) => (b.hours_before_landfall ?? 0) - (a.hours_before_landfall ?? 0))

  return (
    <section className="mt-5">
      <h3 className={HEADING}>Insurance (illustrative)</h3>
      <p className="mt-1 text-xs text-amber-800">Illustrative: not an actual policy.</p>

      <p className="mt-2 text-xs text-slate-500">
        Pre-positioned at {relativeLabel(props.timestepIndex)} (released so far)
      </p>
      <p className="text-lg font-semibold text-slate-800 tabular-nums">{crore(released)}</p>
      <p className="text-[11px] text-slate-500">
        {paying.length} of {props.shown.length || 29} blocks paid. Released money is never taken
        back, so this only goes up.
      </p>
      <Status state={props.triggers} />

      {headlines.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-slate-700">
          {headlines.map((z) => (
            <li key={z.zone_id}>
              <span className="font-medium">{z.zone_name}</span>: {crore(z.first_trigger_payout_inr)}{' '}
              released {hoursLabel(z.hours_before_landfall ?? 0)}
            </li>
          ))}
        </ul>
      )}

      {upcoming.length > 0 && (
        <div className="mt-2 text-xs">
          <p className="text-slate-500">
            Expected in the next 24 h (forecast; payouts follow the observed hazard only):
          </p>
          <ul className="mt-0.5 space-y-0.5 text-sky-800">
            {upcoming.map((f) => (
              <li key={f.properties.zone_id}>
                {f.properties.zone_name}: tier {f.properties.expected_tier_24h} (
                {TIER_PERCENT[f.properties.expected_tier_24h ?? 0]}), nothing released yet
              </li>
            ))}
          </ul>
        </div>
      )}

      {paying.length > 0 && (
        <ul className="mt-2 space-y-1.5 text-xs">
          {paying.map((f) => {
            const p = f.properties
            const first = firstBy.get(p.zone_id)
            return (
              <li key={p.zone_id} className="rounded border border-slate-200 px-2 py-1">
                <p className="font-medium text-slate-800">{p.zone_name}</p>
                <p className="text-slate-600">
                  Now: {readingLabel(p.metric, p.observed, p.unit)}
                  {p.tier > 0
                    ? ` · tier ${p.tier} (${TIER_PERCENT[p.tier]}) · ${crore(p.payout_estimate_inr)}`
                    : ' · below the first tier'}
                </p>
                <p className="text-slate-800">
                  Released so far: tier {p.released_tier} ({TIER_PERCENT[p.released_tier]}) ·{' '}
                  <span className="font-medium tabular-nums">{crore(p.released_payout_inr)}</span>
                </p>
                {(p.expected_tier_24h ?? 0) > p.released_tier && (
                  <p className="text-sky-800">
                    Expected tier in the next 24 h: {p.expected_tier_24h} (
                    {TIER_PERCENT[p.expected_tier_24h ?? 0]})
                  </p>
                )}
                {first?.first_trigger_timestep && first.first_trigger_metric && (
                  <p className="text-slate-500">
                    First triggered {hoursLabel(first.hours_before_landfall ?? 0)} (
                    {METRIC_LABEL[first.first_trigger_metric].toLowerCase()}, tier{' '}
                    {first.first_trigger_tier})
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      )}
      <Status state={props.summary} />

      <p className="mt-2 text-[11px] text-slate-500">
        Basis risk: the payout follows the hazard reading (90th-percentile wind or surge on the
        block&apos;s inhabited land), not assessed losses, so the two can differ.
      </p>
    </section>
  )
}
