// Colours and plain words for the risk choropleth, card and panel.
import type { Color } from '@deck.gl/core'

import type { RiskDriver } from '../../types/contracts'

/**
 * Fixed 0-1 scale (never rescaled per timestep), so colours compare across the replay. Violet,
 * because red and orange mean impact only.
 */
export const RISK_RAMP: readonly (readonly [number, readonly [number, number, number]])[] = [
  [0, [250, 245, 255]],
  [0.25, [221, 190, 254]],
  [0.5, [167, 113, 238]],
  [0.75, [112, 56, 190]],
  [1, [59, 16, 110]],
]
export const FILL_ALPHA = Math.round(0.7 * 255) // 70 % fill; outlines stay full strength
export const OUTLINE: Color = [71, 85, 105, 200] // slate-600
export const SELECTED_OUTLINE: Color = [6, 182, 212] // cyan-500, as the impact highlight
export const UNSCORED_PICK: Color = [0, 0, 0, 1] // invisible, but pickable for the tooltip
export const HATCH = { line: 'rgba(100, 116, 139, 0.8)', size: 8 } // slate-500

/** Linear interpolation along RISK_RAMP; `alpha` 0-255. */
export function riskColor(score: number, alpha = 255): Color {
  const s = Math.min(1, Math.max(0, score))
  for (let i = 1; i < RISK_RAMP.length; i++) {
    const [x1, c1] = RISK_RAMP[i]
    const [x0, c0] = RISK_RAMP[i - 1]
    if (s <= x1) {
      const t = (s - x0) / (x1 - x0)
      const mix = (k: number) => Math.round(c0[k] + t * (c1[k] - c0[k]))
      return [mix(0), mix(1), mix(2), alpha]
    }
  }
  const last = RISK_RAMP[RISK_RAMP.length - 1][1]
  return [last[0], last[1], last[2], alpha]
}

export const cssColor = ([r, g, b, a = 255]: Color) => `rgb(${r} ${g} ${b} / ${a / 255})`

/** CSS gradient for the legend, from the same ramp. */
export const RAMP_CSS = `linear-gradient(to right, ${RISK_RAMP.map(
  ([x, c]) => `${cssColor([...c])} ${x * 100}%`,
).join(', ')})`

export const DRIVER_LABEL: Record<RiskDriver, string> = {
  surge: 'Storm surge on the land',
  wind: 'Gale-force wind',
  flood: 'Flood susceptibility',
  isolated_facilities: 'Hospitals and shelters cut off',
  cut_roads: 'Roads cut',
  cut_substations: 'Substations cut',
  population_density: 'Population density',
  hospital_access: 'Distance to a hospital',
  low_literacy: 'Low literacy',
  mapped_shelters: 'Few mapped shelters',
}

export const PART_LABEL: Record<string, string> = {
  surge: 'Surge (share of inhabited land ≥ 0.3 m)',
  wind: 'Wind (above gale force)',
  flood: 'Flood susceptibility (adds ×0.1)',
  isolated_facilities: 'Hospitals and shelters cut off',
  cut_roads: 'Road length cut',
  cut_substations: 'Substations cut',
  population_density: 'Population density',
  hospital_access: 'Distance to a hospital',
  low_literacy: 'Low literacy',
  mapped_shelters: 'Few mapped shelters',
}
