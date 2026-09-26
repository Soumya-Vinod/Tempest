// Money and reading labels for the insurance panel (illustrative terms).
import type { TriggerMetric } from '../../types/contracts'

const CRORE = 1e7

/** "₹18.28 crore", Indian digit grouping ("₹1,234.50 crore"). */
export function crore(inr: number): string {
  return `₹${(inr / CRORE).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} crore`
}

export const METRIC_LABEL: Record<TriggerMetric, string> = {
  wind_speed: 'Wind',
  surge_depth: 'Surge',
}

export const TIER_PERCENT = ['0 %', '25 %', '50 %', '100 %']

/** "Surge 2.21 m" / "Wind 34.8 m/s". */
export function readingLabel(metric: TriggerMetric, observed: number, unit: string): string {
  return `${METRIC_LABEL[metric]} ${observed.toFixed(metric === 'surge_depth' ? 2 : 1)} ${unit}`
}

export function hoursLabel(hours: number): string {
  return hours > 0 ? `${hours} h before landfall` : 'at landfall'
}
