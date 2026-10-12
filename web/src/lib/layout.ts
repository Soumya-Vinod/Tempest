// Overlay geometry in px. Single source for the panel/timeline sizes and for the map's fit
// padding and attribution offset, so they can't drift apart. The parts that depend on the
// viewport are in Layout: useLayout re-renders only when a resize crosses a threshold.
import { useSyncExternalStore } from 'react'

export const UI_GAP = 16
export const PANEL_WIDTH = 320
/** The KPI strip over the top of the map; it starts right of MapLibre's zoom buttons. */
export const KPI_HEIGHT = 52
export const KPI_LEFT = UI_GAP + 44
/** Distance from the viewport top to just below the KPI strip. */
export const BELOW_KPI = UI_GAP + KPI_HEIGHT + UI_GAP
/** Room for the folded map legend, which sits just above the timeline. */
export const LEGEND_CLEARANCE = 44
/** Keep the card below MapLibre's navigation control, top-left. */
export const CARD_TOP_CLEARANCE = 128

/** Short viewports (small laptops, 1366x768): the timeline drops its sparkline and step labels. */
const COMPACT_BELOW_PX = 800
/** Below this height the map legend folds. */
const FOLD_BELOW_PX = 900
const RESIZE_DEBOUNCE_MS = 150

export interface Layout {
  /** No sparkline or step labels on the timeline. */
  compactTimeline: boolean
  /** The map legend is folded (the user can still open it). */
  legendFolded: boolean
  timelineHeight: number
  /** Distance from the viewport bottom to the top of the timeline bar, plus a gap. */
  aboveTimeline: number
  /** The floating card slot, bottom-left of the map (pathway card, block risk card). */
  cardBottom: number
}

function layoutFor(height: number): Layout {
  const compactTimeline = height < COMPACT_BELOW_PX
  const timelineHeight = compactTimeline ? 96 : 128
  const aboveTimeline = timelineHeight + 2 * UI_GAP
  return {
    compactTimeline,
    legendFolded: height < FOLD_BELOW_PX,
    timelineHeight,
    aboveTimeline,
    cardBottom: aboveTimeline + LEGEND_CLEARANCE,
  }
}

/** Layouts with the same key are identical: the thresholds crossed are all that matter. */
const keyOf = (l: Layout) => `${l.compactTimeline}|${l.legendFolded}`
const viewportHeight = () => (typeof window === 'undefined' ? 1080 : window.innerHeight)

let current = layoutFor(viewportHeight())
const listeners = new Set<() => void>()

if (typeof window !== 'undefined') {
  let timer = 0
  window.addEventListener('resize', () => {
    clearTimeout(timer)
    timer = window.setTimeout(() => {
      const next = layoutFor(viewportHeight())
      if (keyOf(next) === keyOf(current)) return
      current = next
      for (const l of listeners) l()
    }, RESIZE_DEBOUNCE_MS)
  })
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => void listeners.delete(listener)
}

/** The overlay geometry; re-renders (debounced) only when a resize crosses a threshold. */
export function useLayout(): Layout {
  return useSyncExternalStore(subscribe, () => current)
}

/**
 * The geometry for the viewport right now, for code outside React that runs during a resize
 * (fitting the map), before useLayout has caught up.
 */
export function currentLayout(): Layout {
  const now = layoutFor(viewportHeight())
  return keyOf(now) === keyOf(current) ? current : now
}
