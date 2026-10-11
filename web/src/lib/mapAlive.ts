import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useSyncExternalStore } from 'react'

/**
 * Whether the map can take calls that touch its style. On WebGL context loss MapLibre drops its
 * style (map.style is null) until the context is restored, and getProjection(), hasImage(),
 * addLayer()... throw meanwhile.
 */
export function mapAlive(map: MapLibreMap): boolean {
  return map.style != null
}

/** mapAlive, kept up to date across webglcontextlost / webglcontextrestored. No map: false. */
export function useMapAlive(map: MapLibreMap | null): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      map?.on('webglcontextlost', onChange)
      map?.on('webglcontextrestored', onChange)
      return () => {
        map?.off('webglcontextlost', onChange)
        map?.off('webglcontextrestored', onChange)
      }
    },
    [map],
  )
  return useSyncExternalStore(subscribe, () => (map ? mapAlive(map) : false))
}
