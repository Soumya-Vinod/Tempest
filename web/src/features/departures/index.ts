// Last safe departure (Dev B, v1.3 change pending Dev A): where and by when to move patients out by
// road, for each facility that is cut off at some step.
export { default as DepartureLine } from './DepartureLine'
export { buildRouteLayers } from './layers'
export { type DepartureLookup, useDepartures } from './useDepartures'
export { DEPARTURE_NOTE } from './wording'
