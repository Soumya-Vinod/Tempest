import { css, SEVERITY } from '../../lib/tokens'
import type { KeyMomentKind } from '../../types/contracts'

/**
 * Colour and short caption per key moment kind (the full label is in the tooltip). The map's
 * meanings: the first alert is the first block at risk (violet, as the risk scale), cut-offs are
 * dark red (expected: lighter), landfall is the storm (pink).
 */
export const MOMENT: Record<KeyMomentKind, { color: string; caption: string; legend: string }> = {
  first_alert: { color: 'rgb(124 58 237)', caption: 'First alert', legend: 'First alert' },
  first_expected_isolation: {
    color: css(SEVERITY.act),
    caption: 'first expected cut-off',
    legend: 'First expected cut-off',
  },
  first_actual_isolation: { color: css(SEVERITY.cutOff), caption: 'First cut-off', legend: 'First cut-off' },
  landfall: { color: 'rgb(219 39 119)', caption: 'Landfall', legend: 'Landfall' },
}
export const MOMENT_ORDER: KeyMomentKind[] = ['first_alert', 'first_expected_isolation', 'first_actual_isolation', 'landfall']
