// Colours, sizes and plain words for the impact layers and panel.
import type { Color } from '@deck.gl/core'

import type { HazardType, ImpactStatus } from '../../types/contracts'

/**
 * Isolated differs from cut by shape as well as colour (colour-blind safe): cut and at risk are
 * lines and plain dots; an isolated facility is a target (dark-red core, white gap, thick dark-red
 * ring) inside a pulsing halo. Expected isolation is the same ring, dashed.
 */
export const IMPACT_COLOR = {
  cut: [220, 38, 38], // red-600
  atRisk: [245, 158, 11], // amber-500
  isolated: [127, 29, 29], // red-900
  isolatedGap: [255, 255, 255, 220], // the ring's inside: keeps the target readable on red roads
  isolatedHalo: [127, 29, 29, 60],
  outline: [255, 255, 255],
  highlight: [6, 182, 212], // cyan-500
} satisfies Record<string, Color>

/** Line widths (px) for affected lines. */
export const WIDTH = {
  roadCut: 5,
  roadAtRisk: 3.5,
  powerLineAtRisk: 2.5,
  highlight: 8,
  isolatedRing: 4,
}
/** Point radii (px): at AOI zoom the rings must stand out, so these don't scale with zoom. */
export const RADIUS = {
  atRisk: 5,
  isolatedCore: 4,
  isolatedRing: 10,
  haloMin: 13,
  haloMax: 19,
  highlight: 15,
}
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
export const HAZARD_LABEL: Record<HazardType, string> = {
  wind: 'Wind',
  surge: 'Surge',
  flood: 'Flood',
}

export const cssColor = ([r, g, b, a = 255]: Color) => `rgb(${r} ${g} ${b} / ${a / 255})`
