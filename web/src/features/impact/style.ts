// Colours, sizes and plain words for the impact layers and panel.
import type { Color } from '@deck.gl/core'

import { SELECTION, SEVERITY } from '../../lib/tokens'
import type { HazardType, ImpactStatus } from '../../types/contracts'

/**
 * The three severity tiers, told apart by shape and lightness as well as hue (colour-blind safe):
 * cut off is a static deep-red target (core, white gap, ring), expected to be cut off an amber
 * dashed ring, at risk a small slate dot or line. Cut roads and lines are thin deep red.
 */
export const IMPACT_COLOR = {
  cut: [...SEVERITY.cutOff], // cut roads, lines, substations: the one deep red
  atRisk: [...SEVERITY.watch], // watch: slate
  expected: [...SEVERITY.act], // act soon: desaturated amber
  isolated: [...SEVERITY.cutOff], // cut off: the one deep red
  isolatedGap: [255, 255, 255, 230], // the ring's inside: keeps the target readable on red roads
  outline: [255, 255, 255],
  highlight: [...SELECTION],
} satisfies Record<string, Color>

/** Line widths (px) for affected lines. */
export const WIDTH = {
  roadCut: 2.5,
  roadAtRisk: 1.75,
  powerLineAtRisk: 1.25,
  highlight: 6,
  isolatedRing: 2.5,
}
/** Point radii (px): at AOI zoom the rings must stand out, so these don't scale with zoom. */
export const RADIUS = {
  atRisk: 3,
  cut: 3.5,
  isolatedCore: 3,
  isolatedRing: 8,
  highlight: 13,
}

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
