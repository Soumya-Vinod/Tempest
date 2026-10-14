import { css, SEVERITY } from '../../lib/tokens'
import type { KeyMomentKind } from '../../types/contracts'

/**
 * Colour and short caption per key moment kind (the full label is in the tooltip). The map's
 * meanings: the first alert is the first block at risk (slate-violet, as the risk classes), the
 * first expected cut-off amber (act soon), the first cut-off deep red, landfall the storm (plum).
 */
export const MOMENT: Record<KeyMomentKind, { color: string; caption: string; legend: string }> = {
  first_alert: { color: 'rgb(118 106 168)', caption: 'First alert', legend: 'First alert' },
  first_expected_isolation: {
    color: css(SEVERITY.act),
    caption: 'first expected cut-off',
    legend: 'First expected cut-off',
  },
  first_actual_isolation: { color: css(SEVERITY.cutOff), caption: 'First cut-off', legend: 'First cut-off' },
  landfall: { color: 'rgb(122 74 126)', caption: 'Landfall', legend: 'Landfall' },
}
export const MOMENT_ORDER: KeyMomentKind[] = ['first_alert', 'first_expected_isolation', 'first_actual_isolation', 'landfall']
/** Always captioned on the track (the demo's three beats); other markers only on hover. */
export const ALWAYS_CAPTIONED: KeyMomentKind[] = ['first_alert', 'first_actual_isolation', 'landfall']
