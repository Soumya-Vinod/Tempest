// Isotachs: wind contour lines at the IMD category boundaries, from the same interpolated wind
// grid as the hazard images (raster.ts), so lines and hover values agree. d3-contour returns the
// filled areas above each level; only their outlines are drawn, minus the stretches that run
// along the edge of the hazard grid (the AOI box), which are an artefact of cutting it off.
import { contours } from 'd3-contour'
import type { Feature, MultiPolygon, Position } from 'geojson'

import type { HazardLayer } from '../../types/contracts'
import land from './land.json'
import { interpolatedGrid, type Interpolated } from './raster'
import { IMD_CATEGORIES, MS_TO_KMH } from './style'

/** The IMD category boundaries above a Depression: 50, 62, 89, 118, 166, 221 km/h. */
export const ISOTACH_LEVELS = IMD_CATEGORIES.slice(1).map((c) => ({
  kmh: c.minKmh,
  category: c.name,
}))

export interface Isotach {
  kmh: number
  category: string
  level: number // index into ISOTACH_LEVELS (line weight)
  path: [number, number][] // lon, lat
}

export interface IsotachLabel {
  kmh: number
  category: string
  position: [number, number]
}

/** Every Nth vertex is a label candidate; the first one on land is used. */
const LABEL_STEP = 6

type Pt = [number, number]

function onBorder([x, y]: Position, g: Interpolated): boolean {
  return x <= 0 || y <= 0 || x >= g.width || y >= g.height
}

/** Grid coordinates ([0, width] x [0, height], y down; samples at pixel centres) to lon/lat. */
function toLonLat([x, y]: Position, g: Interpolated): Pt {
  const [west, south, east, north] = g.bounds
  return [west + (x / g.width) * (east - west), north - (y / g.height) * (north - south)]
}

/** A closed ring split into open paths, without segments whose two ends lie on the border. */
function ringPaths(ring: Position[], g: Interpolated): Pt[][] {
  const paths: Pt[][] = []
  let current: Pt[] = []
  for (let i = 1; i < ring.length; i++) {
    const a = ring[i - 1]
    const b = ring[i]
    if (onBorder(a, g) && onBorder(b, g)) {
      if (current.length > 1) paths.push(current)
      current = []
      continue
    }
    if (current.length === 0) current.push(toLonLat(a, g))
    current.push(toLonLat(b, g))
  }
  if (current.length > 1) paths.push(current)
  return paths
}

// --- Land test for label anchors (labels on land only) -------------------------------------------

// land.json is a single MultiPolygon Feature (see the note in layers.ts).
const landPolygons: Position[][][] = (land as Feature<MultiPolygon>).geometry.coordinates

function inRing([x, y]: Pt, ring: Position[]): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

function onLand(p: Pt): boolean {
  return landPolygons.some(
    ([outer, ...holes]) => inRing(p, outer) && !holes.some((hole) => inRing(p, hole)),
  )
}

function labelFor(paths: Pt[][]): Pt | null {
  for (const path of [...paths].sort((a, b) => b.length - a.length)) {
    const mid = Math.floor(path.length / 2)
    // From the middle outwards, every LABEL_STEP vertices.
    for (let k = 0; k <= mid; k += LABEL_STEP) {
      for (const i of [mid - k, mid + k]) {
        if (i >= 0 && i < path.length && onLand(path[i])) return path[i]
      }
    }
  }
  return null
}

// --- Contours, cached per fetched wind layer ------------------------------------------------------

export interface Isotachs {
  lines: Isotach[]
  labels: IsotachLabel[]
}

const cache = new WeakMap<HazardLayer[], Isotachs>()

export function isotachs(cells: HazardLayer[]): Isotachs {
  const hit = cache.get(cells)
  if (hit) return hit
  const g = interpolatedGrid(cells)
  const out: Isotachs = { lines: [], labels: [] }
  if (g) {
    const generator = contours()
      .size([g.width, g.height])
      .thresholds(ISOTACH_LEVELS.map((l) => l.kmh / MS_TO_KMH))
    generator(Array.from(g.values)).forEach((area, level) => {
      const { kmh, category } = ISOTACH_LEVELS[level]
      const paths = area.coordinates.flatMap((polygon) =>
        polygon.flatMap((ring) => ringPaths(ring, g)),
      )
      for (const path of paths) out.lines.push({ kmh, category, level, path })
      const position = labelFor(paths)
      if (position) out.labels.push({ kmh, category, position })
    })
  }
  cache.set(cells, out)
  return out
}
