// The KPI strip's figures for the scrubber's timestep and horizon, each with its change since the
// previous timestep. Everything comes from data the panels already fetch (the previous timestep's
// countdown and risk breakdown come from the same caches), so the strip adds no endpoint.
import { formatPeople } from '../../lib/format'
import { failed } from '../../lib/loadState'
import { useTimeline } from '../../lib/timeline'
import type { Horizon, InsuranceSummary } from '../../types/contracts'
import { type CountdownState, useCountdown } from '../countdown'
import { crore } from '../insurance/format'
import type { Loadable } from '../insurance/useInsurance'
import { SURGE_ESTIMATE_NOTE, surgeWhen, useSurgeTotal } from '../risk'

export type KpiTone = 'neutral' | 'warn' | 'alert'

export interface Kpi {
  id: string
  label: string
  /** null while loading (or when `failed`). */
  value: string | null
  /** Its data request failed: shown as "—" (Data unavailable), never as loading. */
  failed?: boolean
  /**
   * Change since the previous timestep, e.g. "+3"; null when there is none to show: no change, or
   * a rise from zero (the delta would only repeat the value). Always neutral grey.
   */
  delta: string | null
  /** Severity colour, used sparingly: only "cut off now" when above zero. */
  tone?: KpiTone
  /** The landfall countdown: first, prominent but calm. */
  lead?: boolean
  /** Tooltip: caveats and definitions. */
  title?: string
}

/** "+3" / "−2" from `before` to `now`; null for no change or a rise from zero (just the value). */
function delta(
  now: number | null,
  before: number | null,
  format: (abs: number) => string = String,
): string | null {
  if (now === null || before === null) return null
  const n = now - before
  if (n === 0 || before === 0) return null
  return `${n > 0 ? '+' : '−'}${format(Math.abs(n))}`
}

function counts(state: CountdownState): { expected: number; cutOff: number } | null {
  return state.status === 'ok'
    ? { expected: state.data.expected.length, cutOff: state.data.cut_off.length }
    : null
}

export function useKpis(args: {
  timestepIndex: number
  horizon: Horizon
  countdown: CountdownState
  insurance: Loadable<InsuranceSummary>
}): { kpis: Kpi[]; previousLabel: string | null } {
  const { timestepIndex: i, horizon } = args
  const timeline = useTimeline()
  const prevIndex = i > 0 ? i - 1 : null
  const ts = timeline.timesteps[i]
  const prevTs = timeline.timesteps[prevIndex ?? i]
  const prevLabel = prevIndex === null ? null : timeline.label(prevIndex)

  const prevCountdown = useCountdown(prevTs).state
  const now = counts(args.countdown)
  const before = prevIndex === null ? null : counts(prevCountdown)

  const surgeNow = useSurgeTotal(ts, horizon)
  const surgeBefore = useSurgeTotal(prevTs, horizon)
  const surge = typeof surgeNow === 'number' ? surgeNow : null
  const surgePrev = typeof surgeBefore === 'number' ? surgeBefore : null
  const countdownFailed = failed(args.countdown)

  const district = args.insurance.status === 'ok' ? args.insurance.data.district : null
  const released = district?.find((d) => d.timestep === ts)?.released_payout_inr ?? null
  // Loaded without this timestep counts as unavailable too: it would never arrive.
  const releasedFailed = failed(args.insurance) || (district !== null && released === null)
  const releasedPrev =
    prevIndex === null ? null : (district?.find((d) => d.timestep === prevTs)?.released_payout_inr ?? null)

  const hours = timeline.hoursToLandfall(i)
  const kpis: Kpi[] = [
    {
      id: 'landfall',
      label: 'Landfall',
      value: hours > 0 ? `in ${hours} h` : 'now',
      delta: null,
      lead: true,
      title: 'Hours until Cyclone Amphan makes landfall (replay).',
    },
    {
      id: 'surge',
      label: horizon === 24 ? 'People in ≥0.3 m surge (24 h)' : 'People in ≥0.3 m surge',
      value: surge === null ? null : formatPeople(surge),
      failed: surgeNow === 'unavailable',
      delta: prevIndex === null ? null : delta(surge, surgePrev, (n) => formatPeople(n).replace('~', '')),
      title: `Residents of areas with at least 0.3 m of storm surge (${surgeWhen(horizon)}). ${SURGE_ESTIMATE_NOTE}`,
    },
    {
      id: 'expected',
      label: 'Expected to be cut off',
      value: now ? String(now.expected) : null,
      failed: countdownFailed,
      delta: now && before ? delta(now.expected, before.expected) : null,
      title: 'Hospitals, health centres and shelters expected to be cut off within the next 24 h (not yet).',
    },
    {
      id: 'cut-off',
      label: 'Cut off now',
      value: now ? String(now.cutOff) : null,
      failed: countdownFailed,
      delta: now && before ? delta(now.cutOff, before.cutOff) : null,
      tone: now && now.cutOff > 0 ? 'alert' : 'neutral',
      title: 'Hospitals, health centres and shelters already cut off from the road network.',
    },
    {
      id: 'released',
      label: '₹ released so far',
      value: released === null ? null : crore(released),
      failed: releasedFailed,
      delta: delta(released, releasedPrev, crore),
      title: 'Illustrative parametric insurance: payouts released so far (never taken back).',
    },
  ]
  return { kpis, previousLabel: prevLabel }
}
