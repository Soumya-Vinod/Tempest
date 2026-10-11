// The insurance panel's per-block rows and their total. The headline is this total, so the list
// always sums to it; in dev it is also checked against the API's district total.
import type { InsuranceSummary, InsuranceZoneSummary, TriggerEvent } from '../../types/contracts'

export interface PayingRow {
  trigger: TriggerEvent['properties']
  /** The block's first trigger (from /summary), if loaded. */
  first: InsuranceZoneSummary | null
  /** The current reading is below the released tier: released money is never taken back. */
  keptHigher: boolean
  /** Released so far is more than the first release (a later tier upgrade). */
  toppedUp: boolean
}

export interface PayingRows {
  rows: PayingRow[]
  /** Sum of the rows' released_payout_inr: the headline figure. */
  total: number
}

/** Blocks with money released so far, largest first. */
export function payingRows(shown: TriggerEvent[], zones: InsuranceZoneSummary[]): PayingRows {
  const firstBy = new Map(zones.map((z) => [z.zone_id, z]))
  const rows = shown
    .filter((f) => f.properties.released_tier > 0)
    .sort((a, b) => b.properties.released_payout_inr - a.properties.released_payout_inr)
    .map((f) => {
      const p = f.properties
      const first = firstBy.get(p.zone_id) ?? null
      return {
        trigger: p,
        first,
        keptHigher: p.tier < p.released_tier,
        toppedUp: first !== null && p.released_payout_inr > first.first_trigger_payout_inr,
      }
    })
  return { rows, total: rows.reduce((sum, r) => sum + r.trigger.released_payout_inr, 0) }
}

const TOLERANCE_INR = 1

/**
 * Dev check: the rows' total is the API's district total for the timestep. Returns the mismatch
 * message, or null when they agree (or the summary has no entry for the timestep).
 */
export function totalMismatch(
  total: number,
  summary: InsuranceSummary,
  timestep: string,
): string | null {
  const district = summary.district.find((d) => d.timestep === timestep)
  if (!district || Math.abs(district.released_payout_inr - total) <= TOLERANCE_INR) return null
  return `insurance: per-block released total ${total} != district total ${district.released_payout_inr} at ${timestep}`
}
