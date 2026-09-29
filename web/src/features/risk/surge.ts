// People in the surge zone (v1.3): wording shared by the district headline and the block card.
import type { Horizon } from '../../types/contracts'

/** How the estimate is made (also in About the data, under Modelled). */
export const SURGE_ESTIMATE_NOTE = 'Estimate: 2011 population, spread evenly over inhabited land.'

/** "Now" or, on the expected hazard, the worst case over the next 24 h. */
export function surgeWhen(horizon: Horizon): string {
  return horizon === 24 ? 'worst case over the next 24 h' : 'now'
}
