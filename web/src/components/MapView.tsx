import type { DeckProps, LayersList } from '@deck.gl/core'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { AttributionControl, Map as MapLibreMap, NavigationControl, setWorkerUrl } from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { useEffect, useRef, type CSSProperties } from 'react'

import { AOI_BBOX, BASEMAP_STYLE_URL } from '../lib/constants'
import { ABOVE_TIMELINE } from '../lib/layout'
import { fitAoi } from '../lib/mapFit'

// Production: MapLibre derives the worker URL from import.meta.url at runtime, which Vite
// can't see, so the build never emits the worker. `?worker&url` makes Vite bundle it (with
// maplibre-gl-shared.mjs inlined) and return its URL; pass that to MapLibre explicitly.
setWorkerUrl(maplibreWorkerUrl)

const [MIN_LON, MIN_LAT, MAX_LON, MAX_LAT] = AOI_BBOX

interface Props {
  /** deck.gl layers from the features, drawn in order (first = bottom). */
  layers?: LayersList
  getTooltip?: DeckProps['getTooltip']
  /** Called for every click, with info.object unset when nothing was picked. */
  onClick?: DeckProps['onClick']
  /** Called once the style has loaded, for features that add MapLibre sources and layers. */
  onMapLoad?: (map: MapLibreMap) => void
}

export default function MapView({ layers = [], getTooltip, onClick, onMapLoad }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<MapboxOverlay | null>(null)
  // Latest onMapLoad without re-creating the map when the callback changes.
  const onMapLoadRef = useRef(onMapLoad)
  useEffect(() => {
    onMapLoadRef.current = onMapLoad
  }, [onMapLoad])

  useEffect(() => {
    if (!containerRef.current) return
    const map = new MapLibreMap({
      container: containerRef.current,
      style: BASEMAP_STYLE_URL,
      // Rough AOI view until the real fit runs on `load`.
      center: [(MIN_LON + MAX_LON) / 2, (MIN_LAT + MAX_LAT) / 2],
      zoom: 8,
      attributionControl: false,
    })
    map.addControl(new NavigationControl(), 'top-left')
    // Bottom-left, lifted above the timeline bar via .maplibregl-ctrl-bottom-left in index.css.
    map.addControl(new AttributionControl({ compact: true }), 'bottom-left')

    // Fit once the container has its real size, and keep re-fitting on resize until the
    // user first pans/zooms. User-initiated moves carry an originalEvent; fitAoi's don't.
    let loaded = false
    let userMoved = false
    map.on('movestart', (e) => {
      if (e.originalEvent) userMoved = true
    })
    map.on('load', () => {
      loaded = true
      fitAoi(map)
      onMapLoadRef.current?.(map)
    })
    map.on('resize', () => {
      if (loaded && !userMoved) fitAoi(map)
    })

    // deck.gl layers render on top of the basemap; features supply them via props.
    const overlay = new MapboxOverlay({ interleaved: false, layers: [] })
    map.addControl(overlay)
    overlayRef.current = overlay

    return () => {
      overlayRef.current = null
      map.removeControl(overlay)
      map.remove()
    }
  }, [])

  // Runs after the effect above on mount, and whenever a feature changes its layers. deck.gl
  // diffs layers by id, so unchanged layers keep their GPU buffers.
  useEffect(() => {
    overlayRef.current?.setProps({ layers, getTooltip, onClick })
  }, [layers, getTooltip, onClick])

  // MapLibre adds .maplibregl-map (position: relative) to its container, so positioning
  // lives on the wrapper and the container only fills it.
  return (
    <div
      className="absolute inset-0 isolate"
      style={{ '--map-ctrl-bottom': `${ABOVE_TIMELINE}px` } as CSSProperties}
    >
      <div ref={containerRef} className="h-full w-full" />
    </div>
  )
}
