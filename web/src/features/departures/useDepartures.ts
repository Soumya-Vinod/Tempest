import { useEffect, useState } from 'react'

import { getDepartures } from '../../lib/api'
import type { Departure } from '../../types/contracts'

export type DepartureLookup = Map<string, Departure>

let loaded: Promise<DepartureLookup> | null = null

/** Last safe departures by facility id (v1.3): not time-dependent, loaded once. Empty until
 *  loaded, or if the route is unavailable (the card and countdown then just omit the line). */
export function useDepartures(): DepartureLookup {
  const [lookup, setLookup] = useState<DepartureLookup>(new Map())
  useEffect(() => {
    let live = true
    loaded ??= getDepartures().then((d) => new Map(d.departures.map((x) => [x.infra_id, x])))
    loaded.then(
      (m) => live && setLookup(m),
      () => {
        loaded = null // retry on next mount
      },
    )
    return () => {
      live = false
    }
  }, [])
  return lookup
}
