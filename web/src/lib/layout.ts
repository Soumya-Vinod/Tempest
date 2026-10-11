// Overlay geometry in px. Single source for the panel/timeline sizes and for the
// map's fit padding and attribution offset, so they can't drift apart.
export const UI_GAP = 16
export const PANEL_WIDTH = 320
export const TIMELINE_HEIGHT = 104
/** The KPI strip over the top of the map; it starts right of MapLibre's zoom buttons. */
export const KPI_HEIGHT = 52
export const KPI_LEFT = UI_GAP + 44
/** Distance from the viewport top to just below the KPI strip. */
export const BELOW_KPI = UI_GAP + KPI_HEIGHT + UI_GAP

/** Distance from the viewport bottom to the top of the timeline bar, plus a gap. */
export const ABOVE_TIMELINE = TIMELINE_HEIGHT + 2 * UI_GAP

/** Room for the folded map legend, which sits just above the timeline. */
export const LEGEND_CLEARANCE = 44

/** The floating card slot, bottom-left of the map (pathway card, block risk card). */
export const CARD_BOTTOM = ABOVE_TIMELINE + LEGEND_CLEARANCE
/** Keep the card below MapLibre's navigation control, top-left. */
export const CARD_TOP_CLEARANCE = 128
