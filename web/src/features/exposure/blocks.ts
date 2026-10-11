// Which CD block a feature lies in, for labelling unnamed features ("Road segment · Kultali").
// Lazy: only hovered features are looked up (bbox prefilter, then point-in-polygon), and each
// answer is memoized by feature id. Nothing is precomputed for the 8,000+ roads.
import type { AreaGeometry, InfraGeometry } from '../../types/contracts'

type Ring = number[][]
type BBox = [minX: number, minY: number, maxX: number, maxY: number]

interface BlockShape {
  name: string
  bbox: BBox
  polygons: Ring[][] // each polygon: outer ring, then holes
}

export interface BlockArea {
  name: string
  geometry: AreaGeometry
}

/** The block a feature lies in, or null (outside every block, e.g. Kolkata). */
export type BlockOf = (id: string, geometry: InfraGeometry) => string | null

function bboxOf(polygons: Ring[][]): BBox {
  const box: BBox = [Infinity, Infinity, -Infinity, -Infinity]
  for (const poly of polygons)
    for (const [x, y] of poly[0]) {
      box[0] = Math.min(box[0], x)
      box[1] = Math.min(box[1], y)
      box[2] = Math.max(box[2], x)
      box[3] = Math.max(box[3], y)
    }
  return box
}

/** Even-odd ray casting. */
function inRing([x, y]: number[], ring: Ring): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

function inShape(p: number[], s: BlockShape): boolean {
  const [x, y] = p
  if (x < s.bbox[0] || y < s.bbox[1] || x > s.bbox[2] || y > s.bbox[3]) return false
  return s.polygons.some((poly) => inRing(p, poly[0]) && !poly.slice(1).some((h) => inRing(p, h)))
}

/** A representative point: the point itself, or a line's middle vertex. */
function anchor(g: InfraGeometry): number[] {
  if (g.type === 'Point') return g.coordinates
  const line = g.type === 'LineString' ? g.coordinates : g.coordinates[0]
  return line[Math.floor(line.length / 2)]
}

export function createBlockOf(areas: BlockArea[]): BlockOf {
  const shapes: BlockShape[] = areas.map(({ name, geometry }) => {
    const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
    return { name, polygons, bbox: bboxOf(polygons) }
  })
  const memo = new Map<string, string | null>()
  return (id, geometry) => {
    if (memo.has(id)) return memo.get(id)!
    const p = anchor(geometry)
    const name = shapes.find((s) => inShape(p, s))?.name ?? null
    memo.set(id, name)
    return name
  }
}
