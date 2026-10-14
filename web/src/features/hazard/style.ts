// Hazard map styling: surge (sequential blue, fixed 0–6 m), wind (IMD categories in km/h) and
// flood susceptibility (muted, static). Colours are [r, g, b, a] for deck.gl.
import type { Color } from '@deck.gl/core'

import { HAZARD_RAMP, NEUTRAL } from '../../lib/tokens'

export const MS_TO_KMH = 3.6
export const toKmh = (ms: number) => ms * MS_TO_KMH

// --- Surge ---------------------------------------------------------------------------------------

/** Cells at or below this depth (m) are not drawn. */
export const SURGE_MIN_M = 0.05
/** Fixed scale, comparable across timesteps: the hazard model's physical ceiling (6 m). */
export const SURGE_MAX_M = 6
/** The hazard ramp (design tokens): light blue to deep indigo. */
const SURGE_STOPS: [number, number, number][] = HAZARD_RAMP.map(([r, g, b]) => [r, g, b])
const SURGE_ALPHA = [60, 175] as const // modest opacity, rising with depth

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t
}

function ramp(stops: [number, number, number][], t: number): [number, number, number] {
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1)
  const i = Math.min(Math.floor(x), stops.length - 2)
  const f = x - i
  return [0, 1, 2].map((k) => Math.round(lerp(stops[i][k], stops[i + 1][k], f))) as [
    number,
    number,
    number,
  ]
}

function surgeRgba(depthM: number): [number, number, number, number] {
  const t = depthM / SURGE_MAX_M
  return [...ramp(SURGE_STOPS, t), Math.round(lerp(SURGE_ALPHA[0], SURGE_ALPHA[1], Math.min(t, 1)))]
}

export const SURGE_RAMP_CSS = `linear-gradient(to right, ${SURGE_STOPS.map(
  ([r, g, b], i) =>
    `rgba(${r}, ${g}, ${b}, ${lerp(SURGE_ALPHA[0], SURGE_ALPHA[1], i / (SURGE_STOPS.length - 1)) / 255})`,
).join(', ')})`
export const SURGE_TICKS_M = [0, 2, 4, 6]

// --- Wind: IMD categories (knots converted to km/h) ---------------------------------------------

export interface ImdCategory {
  name: string
  /** Lower bound, km/h (IMD's knot thresholds: 17, 28, 34, 48, 64, 90, 120 kt). */
  minKmh: number
}

export const IMD_CATEGORIES: ImdCategory[] = [
  { name: 'Depression', minKmh: 31 },
  { name: 'Deep Depression', minKmh: 50 },
  { name: 'Cyclonic Storm', minKmh: 62 },
  { name: 'Severe Cyclonic Storm', minKmh: 89 },
  { name: 'Very Severe Cyclonic Storm', minKmh: 118 },
  { name: 'Extremely Severe Cyclonic Storm', minKmh: 166 },
  { name: 'Super Cyclonic Storm', minKmh: 221 },
]

/** The IMD category for a sustained wind speed in km/h; null below a Depression. */
export function imdCategory(kmh: number): ImdCategory | null {
  let found: ImdCategory | null = null
  for (const c of IMD_CATEGORIES) if (kmh >= c.minKmh) found = c
  return found
}

// Wind is drawn as isotachs (contours.ts): dark slate lines at the category boundaries, heavier
// for higher categories. No fill colour: red and orange are reserved for impact, and a fill
// would hide the surge underneath.
export const ISOTACH_COLOR: Color = [...NEUTRAL.muted, 190]
export const ISOTACH_CSS = 'rgb(71 85 105)'
export const ISOTACH_LABEL_BG: Color = [255, 255, 255, 200]
/** Line width in px for isotach level 0 (50 km/h) … 5 (221 km/h): thin, a little heavier higher. */
export const isotachWidth = (level: number) => 0.75 + 0.3 * level

// --- Flood susceptibility (static, muted) --------------------------------------------------------

// A quiet neutral wash, low opacity: context under the surge, never a warning colour.
const FLOOD_STOPS: [number, number, number][] = [
  [226, 232, 240],
  [176, 186, 200],
  [128, 140, 158],
]
const FLOOD_ALPHA = [12, 70] as const

export function floodColor(severity: number): Color {
  return [...ramp(FLOOD_STOPS, severity), Math.round(lerp(FLOOD_ALPHA[0], FLOOD_ALPHA[1], severity))]
}

export const FLOOD_RAMP_CSS = `linear-gradient(to right, ${FLOOD_STOPS.map(
  ([r, g, b], i) =>
    `rgba(${r}, ${g}, ${b}, ${lerp(FLOOD_ALPHA[0], FLOOD_ALPHA[1], i / (FLOOD_STOPS.length - 1)) / 255})`,
).join(', ')})`

// --- Storm track ---------------------------------------------------------------------------------
// The storm is a muted plum, soft and thin: a hue no other symbol uses (deep red / amber are
// severity, slate-violet the risk fill, blue the surge, slate the network).

export const TRACK_COLOR: Color = [122, 74, 126, 200] // #7a4a7e
export const TRACK_FUTURE_COLOR: Color = [122, 74, 126, 95]
/** The next 24 h of track: where the storm will be while today's decisions play out. */
export const TRACK_NEXT_COLOR: Color = [146, 88, 150, 225] // #925896
export const TRACK_NEXT_H = 24
export const TRACK_WIDTH = { past: 2, next: 2.75, later: 1.5 }
export const STORM_HALO: Color = [146, 88, 150, 45]
export const STORM_FILL: Color = [122, 74, 126, 235]
/** The same colours for the legend and the off-screen arrow. */
export const STORM_CSS = {
  track: 'rgb(122 74 126 / 0.8)',
  next: 'rgb(146 88 150 / 0.9)',
  later: 'rgb(122 74 126 / 0.4)',
  storm: 'rgb(122 74 126)',
} as const
export const STORM_OUTLINE: Color = [255, 255, 255, 255]
/** White casing each side of every track segment (keeps it apart from roads). */
export const TRACK_CASING: Color = [255, 255, 255, 200]
export const TRACK_CASING_PX = 1

// --- Smoothed images (raster.ts): the same scales, per pixel ------------------------------------
// Module-level functions: raster.ts caches images per function, so they must stay stable.

const SURGE_BASE = SURGE_STOPS[0]

/** Surge pixel: the legend's colour and opacity; transparent at or below SURGE_MIN_M. */
export function surgePixel(depthM: number): [number, number, number, number] {
  if (depthM <= SURGE_MIN_M) return [...SURGE_BASE, 0]
  return surgeRgba(depthM)
}
