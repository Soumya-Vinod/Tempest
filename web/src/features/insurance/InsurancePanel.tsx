import { useEffect } from 'react'

import { useTimeline } from '../../lib/timeline'
import type { InsuranceSummary, TriggerEvent } from '../../types/contracts'
import { crore, hoursLabel, METRIC_LABEL, readingLabel, TIER_PERCENT } from './format'
import { payingRows, totalMismatch } from './rows'
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
 * "Insurance (illustrative)": the district total released so far (released amounts only go up)
 * and, per paying block, what it has released so far, when it was first released and the current
 * reading. The headline is the sum of the rows, so the two always reconcile.
 */
export default function InsurancePanel(props: InsurancePanelProps) {
  const timeline = useTimeline()
  const timestep = timeline.timesteps[props.timestepIndex]
  const zones = props.summary.status === 'ok' ? props.summary.data.zones : []
  const { rows, total } = payingRows(props.shown, zones)
  // Blocks the expected hazard (next 24 h) would trigger that haven't been paid yet (v1.3).
  const upcoming = props.shown
    .filter((f) => f.properties.released_tier === 0 && (f.properties.expected_tier_24h ?? 0) > 0)
    .sort((a, b) => (b.properties.expected_tier_24h ?? 0) - (a.properties.expected_tier_24h ?? 0))

  // Dev only: the rows must add up to the API's district total for this timestep.
  const settled = props.triggers.status === 'ok' && props.summary.status === 'ok'
  const mismatch =
    import.meta.env.DEV && settled && props.summary.status === 'ok'
      ? totalMismatch(total, props.summary.data, timestep)
      : null
  useEffect(() => {
    if (mismatch) console.error(mismatch)
  }, [mismatch])

  return (
    <section className="mt-5">
      <h3 className={HEADING}>Insurance (illustrative)</h3>
      <p className="mt-1 text-xs text-amber-800">Illustrative: not an actual policy.</p>

      <p className="mt-2 text-xs text-slate-500">
        Released so far, at {timeline.label(props.timestepIndex)}
      </p>
      <p className="text-lg font-semibold text-slate-800 tabular-nums">{crore(total)}</p>
      <p className="text-[11px] text-slate-500">
        {rows.length} of {props.shown.length || 29} blocks paid; the amounts below add up to this
        total. Released money is never taken back, so it only goes up.
      </p>
      <Status state={props.triggers} />

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

      {rows.length > 0 && (
        <ul className="mt-2 space-y-1.5 text-xs">
          {rows.map(({ trigger: p, first, keptHigher, toppedUp }) => (
            <li key={p.zone_id} className="rounded border border-slate-200 px-2 py-1">
              <p className="flex items-baseline gap-2">
                <span className="font-medium text-slate-800">{p.zone_name}</span>
                <span className="ml-auto font-medium text-slate-800 tabular-nums">
                  {crore(p.released_payout_inr)}
                </span>
              </p>
              <p className="text-slate-600">
                Released so far: tier {p.released_tier} ({TIER_PERCENT[p.released_tier]})
              </p>
              {first?.first_trigger_timestep && first.first_trigger_metric && (
                <p className="text-slate-500">
                  {toppedUp ? 'First released ' : 'Released '}
                  {toppedUp && <span className="tabular-nums">{crore(first.first_trigger_payout_inr)} </span>}
                  {hoursLabel(first.hours_before_landfall ?? 0)} (
                  {METRIC_LABEL[first.first_trigger_metric].toLowerCase()}, tier{' '}
                  {first.first_trigger_tier}){toppedUp && '; topped up since'}
                </p>
              )}
              <p className="text-slate-500">
                Now: {readingLabel(p.metric, p.observed, p.unit)}
                {p.tier > 0 ? ` · tier ${p.tier}` : ' · below the first tier'}
                {keptHigher &&
                  ` · lower than the released tier ${p.released_tier}: released money is never taken back`}
              </p>
              {(p.expected_tier_24h ?? 0) > p.released_tier && (
                <p className="text-sky-800">
                  Expected tier in the next 24 h: {p.expected_tier_24h} (
                  {TIER_PERCENT[p.expected_tier_24h ?? 0]})
                </p>
              )}
            </li>
          ))}
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
