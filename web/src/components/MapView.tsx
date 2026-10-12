import type { DeckProps, LayersList } from '@deck.gl/core'
import { MapboxOverlay } from '@deck.gl/mapbox'
import { AttributionControl, Map as MapLibreMap, NavigationControl, setWorkerUrl } from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { useEffect, useRef, type CSSProperties } from 'react'

import { AOI_BBOX, BASEMAP_STYLE_URL } from '../lib/constants'
import { above, cssLength, useLayout } from '../lib/layout'
import { mapAlive } from '../lib/mapAlive'
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
  /** Called when the map is removed (unmount, or a remount after a map error). */
  onMapRemove?: () => void
}

type OverlayProps = Pick<DeckProps, 'layers' | 'getTooltip' | 'onClick'>

export default function MapView({ layers = [], getTooltip, onClick, onMapLoad, onMapRemove }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const overlayRef = useRef<MapboxOverlay | null>(null)
  // The latest overlay props, re-applied when a lost WebGL context is restored.
  const propsRef = useRef<OverlayProps>({ layers: [] })
  // Latest callbacks without re-creating the map when they change.
  const layout = useLayout()
  const onMapLoadRef = useRef(onMapLoad)
  const onMapRemoveRef = useRef(onMapRemove)
  useEffect(() => {
    onMapLoadRef.current = onMapLoad
    onMapRemoveRef.current = onMapRemove
  }, [onMapLoad, onMapRemove])

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
    // Bottom-right of the map area (the legend has the bottom-left), lifted above the timeline
    // and left of the side panel via .maplibregl-ctrl-bottom-right in index.css.
    map.addControl(new AttributionControl({ compact: true }), 'bottom-right')

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
    // WebGL context loss: MapLibre drops its style until the context is restored, and the deck.gl
    // overlay sync (setProps -> map.getProjection) would throw meanwhile, so it is skipped then
    // (see the layers effect) and the latest props are applied again here.
    map.on('webglcontextrestored', () => {
      if (mapAlive(map)) overlayRef.current?.setProps(propsRef.current)
    })

    // deck.gl layers render on top of the basemap; features supply them via props.
    const overlay = new MapboxOverlay({ interleaved: false, layers: [] })
    map.addControl(overlay)
    mapRef.current = map
    overlayRef.current = overlay

    return () => {
      overlayRef.current = null
      mapRef.current = null
      map.removeControl(overlay)
      map.remove()
      onMapRemoveRef.current?.()
    }
  }, [])

  // Runs after the effect above on mount, and whenever a feature changes its layers. deck.gl
  // diffs layers by id, so unchanged layers keep their GPU buffers. Skipped while the WebGL
  // context is lost; the restore handler applies the latest props.
  useEffect(() => {
    propsRef.current = { layers, getTooltip, onClick }
    const map = mapRef.current
    if (map && mapAlive(map)) overlayRef.current?.setProps(propsRef.current)
  }, [layers, getTooltip, onClick])

  // MapLibre adds .maplibregl-map (position: relative) to its container, so positioning
  // lives on the wrapper and the container only fills it.
  return (
    <div
      className="absolute inset-0 isolate"
      style={
        {
          // Phones: above the legend's row, which spans most of the width.
          '--map-ctrl-bottom': cssLength(
            above(layout, layout.phone ? layout.cardBottom : layout.aboveTimeline),
          ),
          '--map-ctrl-right': `${layout.mapRight}px`,
        } as CSSProperties
      }
    >
      <div ref={containerRef} className="h-full w-full" />
    </div>
  )
}
