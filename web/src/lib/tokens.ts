// Design tokens for deck.gl and inline SVG, which can't read CSS variables. The same values are
// the Tailwind theme in index.css (@theme); keep the two in step.
//
// Calm control room: neutral base, hazard on one cool ramp, and severity colour kept scarce. Three
// severity tiers only, told apart by lightness and shape as well as hue (deuteranopia-safe):
//   watch    slate, a small dot            L* 48
//   act      desaturated amber, dashed ring L* 63 (text: L* 43)
//   cut off  one deep red, a target         L* 31
// Nothing else on the map or in the panels uses red or orange.

export type Rgb = readonly [number, number, number]

/** Text and surfaces (on white: ink 14.6:1, muted 7.6:1, subtle 4.8:1). */
export const NEUTRAL = {
  ink: [30, 41, 59], // #1e293b
  muted: [71, 85, 105], // #475569
  subtle: [100, 116, 139], // #64748b
  line: [226, 232, 240], // #e2e8f0
  surface: [248, 250, 252], // #f8fafc
} as const satisfies Record<string, Rgb>

export const SEVERITY = {
  /** At risk / watch: slate. */
  watch: [100, 116, 139], // #64748b
  /** Act soon / expected to be cut off: desaturated amber (marker). */
  act: [194, 145, 58], // #c2913a
  /** The same amber dark enough for text on white (5.7:1). */
  actInk: [138, 93, 20], // #8a5d14
  /** Cut off: the one deep red (9.1:1 on white). */
  cutOff: [139, 30, 30], // #8b1e1e
} as const satisfies Record<string, Rgb>

/** Hazard: one cool sequential ramp, light blue to deep indigo. */
export const HAZARD_RAMP: readonly Rgb[] = [
  [219, 231, 243], // #dbe7f3
  [169, 196, 228], // #a9c4e4
  [111, 147, 207], // #6f93cf
  [74, 98, 179], // #4a62b3
  [46, 58, 135], // #2e3a87
]

/** Interactive accent (tabs, primary buttons, links): a quiet navy, 8.3:1 on white. */
export const ACCENT: Rgb = [51, 78, 126] // #334e7e

/** Selection on the map (hovered or picked feature): not a severity colour. */
export const SELECTION: Rgb = [14, 116, 144] // cyan-700

export const css = ([r, g, b]: Rgb, alpha = 1) => `rgb(${r} ${g} ${b} / ${alpha})`
