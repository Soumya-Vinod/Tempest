// Fitting the map to a box while keeping it clear of the side panel (right) and the timeline
// bar (bottom). Used by MapView (the AOI on load / resize) and the hazard Storm section.
import type { LngLatBoundsLike, Map as MapLibreMap, PaddingOptions } from 'maplibre-gl'

import { AOI_BBOX } from './constants'
import { currentLayout, UI_GAP } from './layout'

const [MIN_LON, MIN_LAT, MAX_LON, MAX_LAT] = AOI_BBOX
export const AOI_BOUNDS: LngLatBoundsLike = [
  [MIN_LON, MIN_LAT],
  [MAX_LON, MAX_LAT],
]

/** The map area not covered by the KPI strip, the panel and the timeline, right now. */
function fitPadding(): Required<PaddingOptions> {
  const { belowKpi, gap, mapRight, coveredBottom } = currentLayout()
  return { top: belowKpi + gap, left: 2 * gap, right: mapRight + gap, bottom: coveredBottom + gap }
}
// If the overlays leave less than this (small windows), fit with a plain gap.
const MIN_FIT_PX = 160

export function fitPadded(map: MapLibreMap, bounds: LngLatBoundsLike, animate = false) {
  const { clientWidth: w, clientHeight: h } = map.getContainer()
  if (!w || !h) return
  const p = fitPadding()
  const roomy = w - p.left - p.right >= MIN_FIT_PX && h - p.top - p.bottom >= MIN_FIT_PX
  // No camera flight under prefers-reduced-motion.
  const still = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  map.fitBounds(bounds, { padding: roomy ? p : UI_GAP, animate: animate && !still })
}

export function fitAoi(map: MapLibreMap, animate = false) {
  fitPadded(map, AOI_BOUNDS, animate)
}
