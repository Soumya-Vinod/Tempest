// The KPI strip's figures for the scrubber's timestep and horizon, each with its change since the
// previous timestep. Everything comes from data the panels already fetch (the previous timestep's
// countdown and risk breakdown come from the same caches), so the strip adds no endpoint.
import { formatPeople } from '../../lib/format'
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
  /** null while loading. */
  value: string | null
  /** Change since the previous timestep, e.g. "+3"; null when there is none to show. */
  delta: string | null
  /** The change as a number (sign decides the colour); null when there is none to show. */
  change?: number | null
  /**
   * A rise is bad news (people in surge, facilities cut off): a positive change shows in red.
   * Unset (released money, advisories, landfall): changes stay neutral.
   */
  upIsWorse?: boolean
  tone?: KpiTone
  /** Tooltip: caveats and definitions. */
  title?: string
}

function signed(n: number, format: (abs: number) => string = String): string | null {
  if (n === 0) return '±0'
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
  advisories: { drafts: number; approved: number }
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

  const surge = useSurgeTotal(ts, horizon)
  const surgePrev = useSurgeTotal(prevTs, horizon)

  const district = args.insurance.status === 'ok' ? args.insurance.data.district : null
  const released = district?.find((d) => d.timestep === ts)?.released_payout_inr ?? null
  const releasedPrev =
    prevIndex === null ? null : (district?.find((d) => d.timestep === prevTs)?.released_payout_inr ?? null)

  const hours = timeline.hoursToLandfall(i)
  const kpis: Kpi[] = [
    {
      id: 'landfall',
      label: 'Landfall',
      value: hours > 0 ? `in ${hours} h` : 'now',
      delta: null,
      tone: hours <= 12 ? 'alert' : hours <= 24 ? 'warn' : 'neutral',
      title: 'Hours until Cyclone Amphan makes landfall (replay).',
    },
    {
      id: 'surge',
      label: horizon === 24 ? 'People in ≥0.3 m surge (24 h)' : 'People in ≥0.3 m surge',
      value: surge === null ? null : formatPeople(surge),
      delta: surge !== null && surgePrev !== null && prevIndex !== null ? signed(surge - surgePrev, (n) => formatPeople(n).replace('~', '')) : null,
      change: surge !== null && surgePrev !== null && prevIndex !== null ? surge - surgePrev : null,
      upIsWorse: true,
      title: `Residents of areas with at least 0.3 m of storm surge (${surgeWhen(horizon)}). ${SURGE_ESTIMATE_NOTE}`,
    },
    {
      id: 'expected',
      label: 'Expected to be cut off',
      value: now ? String(now.expected) : null,
      delta: now && before ? signed(now.expected - before.expected) : null,
      change: now && before ? now.expected - before.expected : null,
      upIsWorse: true,
      tone: now && now.expected > 0 ? 'warn' : 'neutral',
      title: 'Hospitals, health centres and shelters expected to be cut off within the next 24 h (not yet).',
    },
    {
      id: 'cut-off',
      label: 'Cut off now',
      value: now ? String(now.cutOff) : null,
      delta: now && before ? signed(now.cutOff - before.cutOff) : null,
      change: now && before ? now.cutOff - before.cutOff : null,
      upIsWorse: true,
      tone: now && now.cutOff > 0 ? 'alert' : 'neutral',
      title: 'Hospitals, health centres and shelters already cut off from the road network.',
    },
    {
      id: 'advisories',
      label: 'Advisories',
      value: `${args.advisories.drafts} pending · ${args.advisories.approved} approved`,
      delta: null,
      title: 'Drafts waiting for approval, and approved advisories, in the queue.',
    },
    {
      id: 'released',
      label: '₹ released so far',
      value: released === null ? null : crore(released),
      delta: released !== null && releasedPrev !== null ? signed(released - releasedPrev, crore) : null,
      title: 'Illustrative parametric insurance: payouts released so far (never taken back).',
    },
  ]
  return { kpis, previousLabel: prevLabel }
}
