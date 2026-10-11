// Geometry shared by everything drawn along the scrubber's track: markers, ticks and the
// sparkline line up with the range thumb's centre.
export const THUMB_PX = 16

/** CSS `left` for a fraction (0..1) of the track, inset by half a thumb on each side. */
export const trackLeft = (fraction: number) =>
  `calc(${THUMB_PX / 2}px + (100% - ${THUMB_PX}px) * ${fraction})`
