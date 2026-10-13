import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useSyncExternalStore } from 'react'

/**
 * The map's zoom, rounded down to a half step, kept up to date at the end of each zoom: callers
 * re-render only when a half step is crossed. `fallback` until the map is up.
 */
export function useZoom(map: MapLibreMap | null, fallback = 9): number {
  const subscribe = useCallback(
    (onChange: () => void) => {
      map?.on('zoomend', onChange)
      return () => void map?.off('zoomend', onChange)
    },
    [map],
  )
  const snapshot = useCallback(() => (map ? Math.floor(map.getZoom() * 2) / 2 : fallback), [map, fallback])
  return useSyncExternalStore(subscribe, snapshot)
}
