import type { Timestep } from '../types/contracts'

/** Contract AOI (contracts.md §1): South 24 Parganas / Sundarbans, EPSG:4326. */
export const AOI_BBOX: [minLon: number, minLat: number, maxLon: number, maxLat: number] = [
  88.0, 21.5, 89.1, 22.7,
]

/** OpenFreeMap Positron: free, keyless vector basemap. */
export const BASEMAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'

const REPLAY_START_MS = Date.UTC(2020, 4, 17, 12) // 2020-05-17T12:00:00Z, T-72h
const REPLAY_STEP_MS = 3 * 60 * 60 * 1000
const REPLAY_STEPS = 25

/**
 * The 25 Amphan replay timesteps (contracts.md §2), T-72h … landfall.
 * Must match Python `REPLAY_TIMESTEPS` in api/app/schemas/common.py.
 * TODO: replace with getTimesteps() once Dev A implements /api/hazard/timesteps.
 */
export const REPLAY_TIMESTEPS: readonly Timestep[] = Array.from({ length: REPLAY_STEPS }, (_, i) =>
  new Date(REPLAY_START_MS + i * REPLAY_STEP_MS).toISOString().replace('.000Z', 'Z'),
)

export const LANDFALL_INDEX = REPLAY_STEPS - 1
export const LANDFALL_TIMESTEP: Timestep = REPLAY_TIMESTEPS[LANDFALL_INDEX]

/** "T-72" … "T-0" for a replay index. */
export function relativeLabel(index: number): string {
  return `T-${(LANDFALL_INDEX - index) * 3}`
}
