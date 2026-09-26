// Smoothed hazard images: the grid values interpolated (bilinear, between cell centres) at
// UPSAMPLE x the grid resolution, then coloured with the same fixed scales as the legends, so the
// colours stay exact (interpolating values, not colours). The canvas is drawn by a BitmapLayer
// with linear filtering, whose bounds put pixel centres on cell centres at UPSAMPLE = 1.
import type { HazardLayer } from '../../types/contracts'

export const UPSAMPLE = 8

export type Bounds = [west: number, south: number, east: number, north: number]

export interface HazardImage {
  image: HTMLCanvasElement
  bounds: Bounds
}

/** [r, g, b, a], 0–255; a = 0 for "not drawn" (keep the rgb of the scale's low end). */
export type Colorize = (value: number) => [number, number, number, number]

interface Grid {
  bounds: Bounds
  cols: number
  rows: number
  /** Row-major from the south-west cell; 0 where a cell is missing. */
  values: Float32Array
}

function cellBounds(f: HazardLayer): Bounds {
  let [w, s, e, n] = [Infinity, Infinity, -Infinity, -Infinity]
  const polygons =
    f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates
  for (const polygon of polygons)
    for (const [x, y] of polygon[0]) {
      w = Math.min(w, x)
      s = Math.min(s, y)
      e = Math.max(e, x)
      n = Math.max(n, y)
    }
  return [w, s, e, n]
}

/** The regular grid behind the cells (Dev A's 0.05° AOI grid), from each cell's bounds. */
function toGrid(cells: HazardLayer[]): Grid | null {
  if (cells.length === 0) return null
  const boxes = cells.map(cellBounds)
  const dx = boxes[0][2] - boxes[0][0]
  const dy = boxes[0][3] - boxes[0][1]
  if (!(dx > 0 && dy > 0)) return null
  const west = Math.min(...boxes.map((b) => b[0]))
  const south = Math.min(...boxes.map((b) => b[1]))
  const east = Math.max(...boxes.map((b) => b[2]))
  const north = Math.max(...boxes.map((b) => b[3]))
  const cols = Math.round((east - west) / dx)
  const rows = Math.round((north - south) / dy)
  const values = new Float32Array(cols * rows)
  boxes.forEach((b, i) => {
    const col = Math.round((b[0] - west) / dx)
    const row = Math.round((b[1] - south) / dy)
    if (col >= 0 && col < cols && row >= 0 && row < rows) {
      values[row * cols + col] = cells[i].properties.value
    }
  })
  return { bounds: [west, south, east, north], cols, rows, values }
}

/** Bilinear value at fractional cell-centre coordinates (x = column, y = row from the south). */
function sample(g: Grid, x: number, y: number): number {
  const cx = Math.min(Math.max(x, 0), g.cols - 1)
  const cy = Math.min(Math.max(y, 0), g.rows - 1)
  const x0 = Math.floor(cx)
  const y0 = Math.floor(cy)
  const x1 = Math.min(x0 + 1, g.cols - 1)
  const y1 = Math.min(y0 + 1, g.rows - 1)
  const fx = cx - x0
  const fy = cy - y0
  const v = (c: number, r: number) => g.values[r * g.cols + c]
  const south = v(x0, y0) * (1 - fx) + v(x1, y0) * fx
  const north = v(x0, y1) * (1 - fx) + v(x1, y1) * fx
  return south * (1 - fy) + north * fy
}

function render(g: Grid, colorize: Colorize): HTMLCanvasElement {
  const width = g.cols * UPSAMPLE
  const height = g.rows * UPSAMPLE
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return canvas
  const img = ctx.createImageData(width, height)
  for (let py = 0; py < height; py++) {
    // Canvas rows run north to south; grid rows south to north.
    const y = (height - py - 0.5) / UPSAMPLE - 0.5
    for (let px = 0; px < width; px++) {
      const [r, gr, b, a] = colorize(sample(g, (px + 0.5) / UPSAMPLE - 0.5, y))
      const o = (py * width + px) * 4
      img.data[o] = r
      img.data[o + 1] = gr
      img.data[o + 2] = b
      img.data[o + 3] = a
    }
  }
  ctx.putImageData(img, 0, 0)
  return canvas
}

// One image per fetched cell array and colour scale: the fetch cache returns the same array for
// a timestep it has seen, so scrubbing back re-uses the image.
const images = new WeakMap<HazardLayer[], Map<Colorize, HazardImage | null>>()

export function hazardImage(cells: HazardLayer[], colorize: Colorize): HazardImage | null {
  let byScale = images.get(cells)
  if (!byScale) images.set(cells, (byScale = new Map()))
  if (!byScale.has(colorize)) {
    const grid = toGrid(cells)
    byScale.set(colorize, grid ? { image: render(grid, colorize), bounds: grid.bounds } : null)
  }
  return byScale.get(colorize) ?? null
}
