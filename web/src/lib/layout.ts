// Overlay geometry in px. Single source for the panel/timeline sizes and for the map's fit
// padding and attribution offset, so they can't drift apart. The parts that depend on the
// viewport are in Layout: useLayout re-renders only when a resize crosses a threshold.
import { useSyncExternalStore } from 'react'

export const UI_GAP = 16
export const PANEL_WIDTH = 320
/** The KPI strip over the top of the map; it starts right of MapLibre's zoom buttons. */
export const KPI_HEIGHT = 52
/** Room for the folded map legend, which sits just above the timeline. */
export const LEGEND_CLEARANCE = 44
/** Keep the card below MapLibre's navigation control, top-left. */
export const CARD_TOP_CLEARANCE = 128
/**
 * Phones: the bottom sheet when it peeks (its handle, the header line and the tab bar). Its
 * current height is the CSS variable --sheet-h (lib/sheet.ts), which the overlays ride on.
 */
export const SHEET_PEEK_PX = 112

/** Narrower than this: the phone layout, with the panel as a bottom sheet. */
const PHONE_BELOW_PX = 768
const PHONE_GAP = 8
/** Short viewports (small laptops, 1366x768): the timeline drops its sparkline and step labels. */
const COMPACT_BELOW_PX = 800
/** Below this height the map legend folds. */
const FOLD_BELOW_PX = 900
const RESIZE_DEBOUNCE_MS = 150

export interface Layout {
  /** The phone layout: the panel is a bottom sheet, the legend starts folded. */
  phone: boolean
  /** The gap between the overlays and around them. */
  gap: number
  /** No sparkline or step labels on the timeline (short viewports, phones). */
  compactTimeline: boolean
  /** The map legend is folded (the user can still open it). */
  legendFolded: boolean
  timelineHeight: number
  /** Distance from the viewport top to just below the KPI strip. */
  belowKpi: number
  kpiLeft: number
  /** Right inset of the map area left free: the side panel and its gaps (phones: a gap). */
  mapRight: number
  /**
   * From the overlays' base (the viewport bottom; on phones the sheet's top edge) to the top of
   * the timeline bar, plus a gap. As a style value: above(layout, aboveTimeline).
   */
  aboveTimeline: number
  /** The floating card slot, bottom-left of the map (pathway card, block risk card); same base. */
  cardBottom: number
  /** The viewport bottom covered by overlays at rest (on phones, with the sheet peeking): map fit. */
  coveredBottom: number
}

function layoutFor(width: number, height: number): Layout {
  const phone = width < PHONE_BELOW_PX
  const gap = phone ? PHONE_GAP : UI_GAP
  const compactTimeline = phone || height < COMPACT_BELOW_PX
  const timelineHeight = compactTimeline ? 96 : 128
  const aboveTimeline = timelineHeight + 2 * gap
  return {
    phone,
    gap,
    compactTimeline,
    legendFolded: phone || height < FOLD_BELOW_PX,
    timelineHeight,
    belowKpi: gap + KPI_HEIGHT + gap,
    kpiLeft: gap + 44,
    mapRight: phone ? gap : PANEL_WIDTH + 2 * gap,
    aboveTimeline,
    cardBottom: aboveTimeline + LEGEND_CLEARANCE,
    // Phones: the legend button and the attribution take a row above the timeline, full width.
    coveredBottom: phone ? SHEET_PEEK_PX + aboveTimeline + LEGEND_CLEARANCE : aboveTimeline,
  }
}

/**
 * A bottom offset `px` above the overlays' base, as a style value: on phones it rides on the
 * bottom sheet as it moves (CSS, so a drag doesn't re-render anything).
 */
export function above(layout: Layout, px: number): number | string {
  return layout.phone ? `calc(var(--sheet-h, ${SHEET_PEEK_PX}px) + ${px}px)` : px
}

/** A style length as CSS text, for calc(). */
export const cssLength = (v: number | string) => (typeof v === 'number' ? `${v}px` : v)

/** Layouts with the same key are identical: the thresholds crossed are all that matter. */
const keyOf = (l: Layout) => `${l.phone}|${l.compactTimeline}|${l.legendFolded}`
const viewport = (): [number, number] =>
  typeof window === 'undefined' ? [1920, 1080] : [window.innerWidth, window.innerHeight]

let current = layoutFor(...viewport())
const listeners = new Set<() => void>()

if (typeof window !== 'undefined') {
  let timer = 0
  window.addEventListener('resize', () => {
    clearTimeout(timer)
    timer = window.setTimeout(() => {
      const next = layoutFor(...viewport())
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
  const now = layoutFor(...viewport())
  return keyOf(now) === keyOf(current) ? current : now
}
