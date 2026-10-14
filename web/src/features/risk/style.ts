// Colours and plain words for the risk choropleth, card and panel.
import type { Color } from '@deck.gl/core'

import { SELECTION } from '../../lib/tokens'
import type { RiskDriver } from '../../types/contracts'

/**
 * Fixed 0-1 scale (never rescaled per timestep), so colours compare across the replay. Four muted
 * classes, a quiet slate-violet (red and orange mean impact only; blue is the hazard view's): the
 * second class starts at the advisory threshold (0.25).
 */
export const RISK_CLASSES: readonly (readonly [number, readonly [number, number, number]])[] = [
  [0, [244, 243, 248]], // #f4f3f8 L* 96
  [0.25, [204, 200, 218]], // #ccc8da L* 81
  [0.5, [149, 144, 179]], // #9590b3 L* 61
  [0.75, [92, 84, 128]], // #5c5480 L* 38
]
export const FILL_ALPHA = Math.round(0.5 * 255) // half-transparent, so impact reads on top
export const OUTLINE: Color = [255, 255, 255, 200] // thin white edges between blocks
export const SELECTED_OUTLINE: Color = [...SELECTION]
export const UNSCORED_PICK: Color = [0, 0, 0, 1] // invisible, but pickable for the tooltip
export const HATCH = { line: 'rgba(100, 116, 139, 0.4)', size: 8 } // slate-500, faint

/** The class colour for a score; `alpha` 0-255. */
export function riskColor(score: number, alpha = 255): Color {
  const s = Math.min(1, Math.max(0, score))
  let c = RISK_CLASSES[0][1]
  for (const [from, colour] of RISK_CLASSES) if (s >= from) c = colour
  return [c[0], c[1], c[2], alpha]
}

export const cssColor = ([r, g, b, a = 255]: Color) => `rgb(${r} ${g} ${b} / ${a / 255})`

/** The unscored-area hatching as a CSS background, for swatches. */
export const HATCH_CSS = `repeating-linear-gradient(-45deg, ${HATCH.line} 0 1.5px, transparent 1.5px 5px)`

/** Stepped CSS gradient for the legend, one band per class. */
export const RAMP_CSS = `linear-gradient(to right, ${RISK_CLASSES.map(([from, c], i) => {
  const to = i + 1 < RISK_CLASSES.length ? RISK_CLASSES[i + 1][0] : 1
  return `${cssColor([...c])} ${from * 100}% ${to * 100}%`
}).join(', ')})`

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
