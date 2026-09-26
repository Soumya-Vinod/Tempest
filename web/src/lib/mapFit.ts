// Fitting the map to a box while keeping it clear of the side panel (right) and the timeline
// bar (bottom). Used by MapView (the AOI on load / resize) and the hazard Storm section.
import type { LngLatBoundsLike, Map as MapLibreMap, PaddingOptions } from 'maplibre-gl'

import { AOI_BBOX } from './constants'
import { ABOVE_TIMELINE, PANEL_WIDTH, UI_GAP } from './layout'

const [MIN_LON, MIN_LAT, MAX_LON, MAX_LAT] = AOI_BBOX
export const AOI_BOUNDS: LngLatBoundsLike = [
  [MIN_LON, MIN_LAT],
  [MAX_LON, MAX_LAT],
]

/** The map area not covered by the panel and the timeline. */
export const FIT_PADDING: Required<PaddingOptions> = {
  top: 2 * UI_GAP,
  left: 2 * UI_GAP,
  right: PANEL_WIDTH + 3 * UI_GAP,
  bottom: ABOVE_TIMELINE + UI_GAP,
}
// If the overlays leave less than this (small windows), fit with a plain gap.
const MIN_FIT_PX = 160

export function fitPadded(map: MapLibreMap, bounds: LngLatBoundsLike, animate = false) {
  const { clientWidth: w, clientHeight: h } = map.getContainer()
  if (!w || !h) return
  const p = FIT_PADDING
  const roomy = w - p.left - p.right >= MIN_FIT_PX && h - p.top - p.bottom >= MIN_FIT_PX
  map.fitBounds(bounds, { padding: roomy ? p : UI_GAP, animate })
}

export function fitAoi(map: MapLibreMap, animate = false) {
  fitPadded(map, AOI_BOUNDS, animate)
}
