import type { KeyMomentKind } from '../../types/contracts'

/** Colour and short caption per key moment kind (the full label is in the tooltip). */
export const MOMENT: Record<KeyMomentKind, { color: string; caption: string; legend: string }> = {
  first_alert: { color: 'rgb(245 158 11)', caption: 'First alert', legend: 'First alert' },
  first_expected_isolation: {
    color: 'rgb(139 92 246)',
    caption: 'first expected cut-off',
    legend: 'First expected cut-off',
  },
  first_actual_isolation: { color: 'rgb(127 29 29)', caption: 'First cut-off', legend: 'First cut-off' },
  landfall: { color: 'rgb(30 41 59)', caption: 'Landfall', legend: 'Landfall' },
}
export const MOMENT_ORDER: KeyMomentKind[] = ['first_alert', 'first_expected_isolation', 'first_actual_isolation', 'landfall']
