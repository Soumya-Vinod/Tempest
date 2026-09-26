// Hazard map styling: surge (sequential blue, fixed 0–6 m), wind (IMD categories in km/h) and
// flood susceptibility (muted, static). Colours are [r, g, b, a] for deck.gl.
import type { Color } from '@deck.gl/core'

export const MS_TO_KMH = 3.6
export const toKmh = (ms: number) => ms * MS_TO_KMH

// --- Surge ---------------------------------------------------------------------------------------

/** Cells at or below this depth (m) are not drawn. */
export const SURGE_MIN_M = 0.05
/** Fixed scale, comparable across timesteps: the hazard model's physical ceiling (6 m). */
export const SURGE_MAX_M = 6
/** Blues, light to dark. */
const SURGE_STOPS: [number, number, number][] = [
  [198, 219, 239],
  [107, 174, 214],
  [33, 113, 181],
  [8, 48, 107],
]
const SURGE_ALPHA = [70, 205] as const // opacity rises with depth

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
  color: [number, number, number]
}

export const IMD_CATEGORIES: ImdCategory[] = [
  { name: 'Depression', minKmh: 31, color: [254, 240, 138] },
  { name: 'Deep Depression', minKmh: 50, color: [253, 224, 71] },
  { name: 'Cyclonic Storm', minKmh: 62, color: [251, 146, 60] },
  { name: 'Severe Cyclonic Storm', minKmh: 89, color: [239, 68, 68] },
  { name: 'Very Severe Cyclonic Storm', minKmh: 118, color: [190, 18, 60] },
  { name: 'Extremely Severe Cyclonic Storm', minKmh: 166, color: [134, 25, 143] },
  { name: 'Super Cyclonic Storm', minKmh: 221, color: [59, 7, 100] },
]
const WIND_ALPHA = 150

/** The IMD category for a sustained wind speed in km/h; null below a Depression. */
export function imdCategory(kmh: number): ImdCategory | null {
  let found: ImdCategory | null = null
  for (const c of IMD_CATEGORIES) if (kmh >= c.minKmh) found = c
  return found
}

export const rgbCss = ([r, g, b]: [number, number, number], alpha = 1) =>
  `rgba(${r}, ${g}, ${b}, ${alpha})`
export const WIND_SWATCH_ALPHA = WIND_ALPHA / 255

// --- Flood susceptibility (static, muted) --------------------------------------------------------

const FLOOD_STOPS: [number, number, number][] = [
  [226, 232, 240],
  [148, 163, 184],
  [71, 104, 116],
]
const FLOOD_ALPHA = [25, 115] as const

export function floodColor(severity: number): Color {
  return [...ramp(FLOOD_STOPS, severity), Math.round(lerp(FLOOD_ALPHA[0], FLOOD_ALPHA[1], severity))]
}

export const FLOOD_RAMP_CSS = `linear-gradient(to right, ${FLOOD_STOPS.map(
  ([r, g, b], i) =>
    `rgba(${r}, ${g}, ${b}, ${lerp(FLOOD_ALPHA[0], FLOOD_ALPHA[1], i / (FLOOD_STOPS.length - 1)) / 255})`,
).join(', ')})`

// --- Storm track ---------------------------------------------------------------------------------

export const TRACK_COLOR: Color = [30, 41, 59, 220]
export const TRACK_FUTURE_COLOR: Color = [30, 41, 59, 150]
export const STORM_FILL: Color = [220, 38, 38, 235]
export const STORM_OUTLINE: Color = [255, 255, 255, 255]

// --- Smoothed images (raster.ts): the same scales, per pixel ------------------------------------
// Module-level functions: raster.ts caches images per function, so they must stay stable.

const SURGE_BASE = SURGE_STOPS[0]
const WIND_BASE = IMD_CATEGORIES[0].color

/** Surge pixel: the legend's colour and opacity; transparent at or below SURGE_MIN_M. */
export function surgePixel(depthM: number): [number, number, number, number] {
  if (depthM <= SURGE_MIN_M) return [...SURGE_BASE, 0]
  return surgeRgba(depthM)
}

/** Wind pixel: the IMD category colour; transparent below a Depression. */
export function windPixel(ms: number): [number, number, number, number] {
  const c = imdCategory(toKmh(ms))
  return c ? [...c.color, WIND_ALPHA] : [...WIND_BASE, 0]
}
