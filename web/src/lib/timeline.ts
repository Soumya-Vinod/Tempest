// The replay timeline (contracts.md §2): a computed fallback, used at once, replaced by
// GET /api/hazard/timesteps when it arrives (components/TimelineProvider.tsx). A cold API start
// never blanks the timeline: everything renders on the fallback until then.
import { createContext, useContext } from 'react'

import type { ReplayTimeline, Timestep } from '../types/contracts'

const HOUR_MS = 60 * 60 * 1000

export interface Timeline {
  /** T-72h … landfall, oldest first. */
  timesteps: readonly Timestep[]
  landfallIndex: number
  /** Index of a timestep; -1 if it isn't one (or is null). */
  indexOf: (timestep: Timestep | null | undefined) => number
  /** Hours from the timestep at `index` to landfall. */
  hoursToLandfall: (index: number) => number
  /** "T-72" … "T-0" for an index. */
  label: (index: number) => string
}

const parse = (ts: Timestep) => Date.parse(ts)

export function buildTimeline(timesteps: readonly Timestep[], landfall: Timestep): Timeline {
  const landfallIndex = Math.max(0, timesteps.indexOf(landfall))
  const landfallMs = parse(landfall)
  const hoursToLandfall = (index: number) =>
    Math.round((landfallMs - parse(timesteps[index])) / HOUR_MS)
  return {
    timesteps,
    landfallIndex,
    indexOf: (ts) => (ts ? timesteps.indexOf(ts) : -1),
    hoursToLandfall,
    label: (index) => `T-${hoursToLandfall(index)}`,
  }
}

// Fallback: must match Python REPLAY_TIMESTEPS in api/app/schemas/common.py.
const FALLBACK_START_MS = Date.UTC(2020, 4, 17, 12) // 2020-05-17T12:00:00Z, T-72h
const FALLBACK_STEP_MS = 3 * HOUR_MS
const FALLBACK_STEPS = 25
const FALLBACK_TIMESTEPS: readonly Timestep[] = Array.from({ length: FALLBACK_STEPS }, (_, i) =>
  new Date(FALLBACK_START_MS + i * FALLBACK_STEP_MS).toISOString().replace('.000Z', 'Z'),
)

export const FALLBACK_TIMELINE = buildTimeline(
  FALLBACK_TIMESTEPS,
  FALLBACK_TIMESTEPS[FALLBACK_STEPS - 1],
)

/** True when the API's timeline is the same as `current` (no re-render needed). */
export function sameTimeline(current: Timeline, api: ReplayTimeline): boolean {
  return (
    current.timesteps[current.landfallIndex] === api.landfall &&
    current.timesteps.length === api.timesteps.length &&
    current.timesteps.every((ts, i) => ts === api.timesteps[i])
  )
}

export const TimelineContext = createContext<Timeline>(FALLBACK_TIMELINE)

export function useTimeline(): Timeline {
  return useContext(TimelineContext)
}
