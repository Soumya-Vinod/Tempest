import type { DeckProps, LayersList } from '@deck.gl/core'
import { MapboxOverlay } from '@deck.gl/mapbox'
import {
  AttributionControl,
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
  type LngLatBoundsLike,
  type PaddingOptions,
} from 'maplibre-gl'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { useEffect, useRef, type CSSProperties } from 'react'

import { AOI_BBOX, BASEMAP_STYLE_URL } from '../lib/constants'
import { ABOVE_TIMELINE, PANEL_WIDTH, UI_GAP } from '../lib/layout'

// Production: MapLibre derives the worker URL from import.meta.url at runtime, which Vite
// can't see, so the build never emits the worker. `?worker&url` makes Vite bundle it (with
// maplibre-gl-shared.mjs inlined) and return its URL; pass that to MapLibre explicitly.
setWorkerUrl(maplibreWorkerUrl)

const [MIN_LON, MIN_LAT, MAX_LON, MAX_LAT] = AOI_BBOX
const AOI_BOUNDS: LngLatBoundsLike = [
  [MIN_LON, MIN_LAT],
  [MAX_LON, MAX_LAT],
]

// Keep the AOI clear of the side panel (right) and the timeline bar (bottom).
const FIT_PADDING: Required<PaddingOptions> = {
  top: 2 * UI_GAP,
  left: 2 * UI_GAP,
  right: PANEL_WIDTH + 3 * UI_GAP,
  bottom: ABOVE_TIMELINE + UI_GAP,
}
// If the overlays leave less than this for the AOI (small windows), fit with a plain gap.
const MIN_FIT_PX = 160

function fitAoi(map: MapLibreMap) {
  const { clientWidth: w, clientHeight: h } = map.getContainer()
  if (!w || !h) return
  const p = FIT_PADDING
  const roomy = w - p.left - p.right >= MIN_FIT_PX && h - p.top - p.bottom >= MIN_FIT_PX
  map.fitBounds(AOI_BOUNDS, { padding: roomy ? p : UI_GAP, animate: false })
}

interface Props {
  /** deck.gl layers from the features, drawn in order (first = bottom). */
  layers?: LayersList
  getTooltip?: DeckProps['getTooltip']
}

export default function MapView({ layers = [], getTooltip }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<MapboxOverlay | null>(null)

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
    overlayRef.current?.setProps({ layers, getTooltip })
  }, [layers, getTooltip])

  // MapLibre adds .maplibregl-map (position: relative) to its container, so positioning
  // lives on the wrapper and the container only fills it.
  return (
    <div
      className="absolute inset-0"
      style={{ '--map-ctrl-bottom': `${ABOVE_TIMELINE}px` } as CSSProperties}
    >
      <div ref={containerRef} className="h-full w-full" />
    </div>
  )
}
