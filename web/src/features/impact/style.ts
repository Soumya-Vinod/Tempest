// Colours, sizes and plain words for the impact layers and panel.
import type { Color } from '@deck.gl/core'

import type { HazardType, ImpactStatus } from '../../types/contracts'

export const IMPACT_COLOR = {
  cut: [220, 38, 38], // red-600
  atRisk: [249, 115, 22], // orange-500
  isolated: [220, 38, 38],
  isolatedFill: [220, 38, 38, 45], // faint fill keeps the whole ring clickable
  outline: [255, 255, 255],
  highlight: [6, 182, 212], // cyan-500
} satisfies Record<string, Color>

/** Line widths (px) for affected lines. */
export const WIDTH = { roadCut: 5, roadAtRisk: 3.5, powerLineAtRisk: 2.5, highlight: 8 }
/** Point radii (px): at AOI zoom the rings must stand out, so these don't scale with zoom. */
export const RADIUS = { atRisk: 5, isolatedMin: 10, isolatedMax: 17, highlight: 15 }
export const PULSE_MS = 900

/** Worst first. */
export const STATUS_RANK: Record<ImpactStatus, number> = { ok: 0, at_risk: 1, cut: 2, isolated: 3 }
export const NON_OK: readonly ImpactStatus[] = ['isolated', 'cut', 'at_risk']

export const STATUS_LABEL: Record<ImpactStatus, string> = {
  ok: 'OK',
  at_risk: 'At risk',
  cut: 'Cut',
  isolated: 'Isolated',
}
export const STATUS_COLOR: Record<ImpactStatus, Color> = {
  ok: [148, 163, 184],
  at_risk: IMPACT_COLOR.atRisk,
  cut: IMPACT_COLOR.cut,
  isolated: IMPACT_COLOR.isolated,
}
export const HAZARD_LABEL: Record<HazardType, string> = {
  wind: 'Wind',
  surge: 'Surge',
  flood: 'Flood',
}

export const cssColor = ([r, g, b, a = 255]: Color) => `rgb(${r} ${g} ${b} / ${a / 255})`
