// Overlay geometry in px. Single source for the panel/timeline sizes and for the
// map's fit padding and attribution offset, so they can't drift apart.
export const UI_GAP = 16
export const PANEL_WIDTH = 320
export const TIMELINE_HEIGHT = 104

/** Distance from the viewport bottom to the top of the timeline bar, plus a gap. */
export const ABOVE_TIMELINE = TIMELINE_HEIGHT + 2 * UI_GAP

/** Room for MapLibre's compact attribution button, which sits just above the timeline. */
export const ATTRIBUTION_CLEARANCE = 44

/** The floating card slot, bottom-left of the map (pathway card, block risk card). */
export const CARD_BOTTOM = ABOVE_TIMELINE + ATTRIBUTION_CLEARANCE
/** Keep the card below MapLibre's navigation control, top-left. */
export const CARD_TOP_CLEARANCE = 128
