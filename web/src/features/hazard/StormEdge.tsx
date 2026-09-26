import type { Map as MapLibreMap } from 'maplibre-gl'
import { useEffect, useState } from 'react'

import { ABOVE_TIMELINE, PANEL_WIDTH, UI_GAP } from '../../lib/layout'

/** Inset of the arrow from the edge of the visible map area, px. */
const EDGE_INSET = 34

interface Placement {
  x: number
  y: number
  angle: number // radians, screen space (0 = right, clockwise)
  km: number
}

const toRad = (d: number) => (d * Math.PI) / 180

/** Great-circle distance in km (haversine). */
function distanceKm(a: [number, number], b: [number, number]): number {
  const [lon1, lat1] = a.map(toRad)
  const [lon2, lat2] = b.map(toRad)
  const h =
    Math.sin((lat2 - lat1) / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2
  return 2 * 6371 * Math.asin(Math.sqrt(h))
}

/**
 * Where to draw the arrow, or null when the storm is inside the part of the map not covered by
 * the side panel and the timeline.
 */
function place(map: MapLibreMap, storm: [number, number]): Placement | null {
  const { clientWidth: w, clientHeight: h } = map.getContainer()
  const right = w - PANEL_WIDTH - 2 * UI_GAP
  const bottom = h - ABOVE_TIMELINE
  if (right <= 2 * EDGE_INSET || bottom <= 2 * EDGE_INSET) return null
  const p = map.project(storm)
  if (p.x >= 0 && p.x <= right && p.y >= 0 && p.y <= bottom) return null
  const cx = right / 2
  const cy = bottom / 2
  const dx = p.x - cx
  const dy = p.y - cy
  const tx = dx === 0 ? Infinity : (cx - EDGE_INSET) / Math.abs(dx)
  const ty = dy === 0 ? Infinity : (cy - EDGE_INSET) / Math.abs(dy)
  const t = Math.min(tx, ty)
  const centre = map.unproject([cx, cy])
  return {
    x: cx + dx * t,
    y: cy + dy * t,
    angle: Math.atan2(dy, dx),
    km: distanceKm([centre.lng, centre.lat], storm),
  }
}

/** An arrow on the map edge towards the storm when it is out of view: distance and category. */
export default function StormEdge(props: {
  map: MapLibreMap | null
  storm: [number, number] | null
  category: string
}) {
  const { map, storm } = props
  const [placement, setPlacement] = useState<Placement | null>(null)

  useEffect(() => {
    if (!map || !storm) return
    let frame = 0
    const update = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => setPlacement(place(map, storm)))
    }
    update()
    map.on('move', update)
    map.on('resize', update)
    return () => {
      cancelAnimationFrame(frame)
      map.off('move', update)
      map.off('resize', update)
    }
  }, [map, storm])

  if (!map || !storm || !placement) return null
  const deg = (placement.angle * 180) / Math.PI
  return (
    <div
      className="pointer-events-none absolute z-10 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center"
      style={{ left: placement.x, top: placement.y }}
      role="status"
      aria-label={`Storm out of view: ${Math.round(placement.km)} km away, ${props.category}`}
    >
      <svg
        width="26"
        height="26"
        viewBox="0 0 26 26"
        style={{ transform: `rotate(${deg}deg)` }}
        aria-hidden
      >
        <path d="M3 13 H19 M13 6 L21 13 L13 20" stroke="#dc2626" strokeWidth="3.5" fill="none" />
      </svg>
      <span className="mt-0.5 rounded bg-white/90 px-1.5 py-0.5 text-[11px] leading-tight font-medium whitespace-nowrap text-slate-800 shadow">
        {Math.round(placement.km).toLocaleString('en-IN')} km · {props.category}
      </span>
    </div>
  )
}
