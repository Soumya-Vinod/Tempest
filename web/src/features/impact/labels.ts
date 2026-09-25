// Plain-word helpers shared by the impact tooltip and panel.
import type { InfraFeature } from '../../types/contracts'
import type { InfraByType } from '../exposure'

export type InfraLookup = Map<string, InfraFeature>

/** Every loaded InfraFeature by id (for names, geometry and baseline attributes). */
export function infraLookup(state: InfraByType): InfraLookup {
  const out: InfraLookup = new Map()
  for (const s of Object.values(state)) {
    if (s.status === 'ok') for (const f of s.data.features) out.set(f.id, f)
  }
  return out
}

export function featureName(id: string, lookup: InfraLookup): string {
  const f = lookup.get(id)
  if (!f) return id
  if (f.properties.name) return f.properties.name
  const a = f.properties.attributes
  if (a.ferry === true) return 'Unnamed ferry route'
  if (a.facility_level === 'health_centre') return 'Unnamed health centre'
  return `Unnamed ${f.properties.infra_type.replace('_', ' ')}`
}

/** 3900 -> "1 h 05 min", 420 -> "7 min". */
export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`
}

/** Baseline access for a hospital or shelter, from its InfraFeature attributes; null otherwise. */
export function baselineAccess(id: string, lookup: InfraLookup): string | null {
  const a = lookup.get(id)?.properties.attributes
  if (!a || !('snap_too_far' in a)) return null
  if (a.snap_too_far === true) return 'More than 2 km from the road network'
  const t = a.baseline_travel_time_s
  return typeof t === 'number'
    ? `Usual travel time from Diamond Harbour: ${formatDuration(t)}`
    : 'No usual road route from Diamond Harbour'
}
