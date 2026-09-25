// Unscored areas as a hatched MapLibre fill (a fill-pattern from a small canvas image), so no new
// dependency is needed. MapLibre layers draw under the deck.gl overlay; the tooltip comes from an
// invisible deck.gl layer over the same polygons (layers.ts).
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl'

import type { UnscoredAreaCollection } from '../../types/contracts'
import { HATCH } from './style'

const IMAGE = 'risk-hatch'
const SOURCE = 'risk-unscored'
const FILL = 'risk-unscored-fill'
const LINE = 'risk-unscored-line'

/** Diagonal lines on a transparent square; repeats seamlessly. */
function hatchImage(size: number): ImageData {
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')!
  ctx.strokeStyle = HATCH.line
  ctx.lineWidth = 1.5
  ctx.beginPath()
  // The main diagonal plus the two corner pieces, so the pattern tiles without gaps.
  for (const offset of [-size, 0, size]) {
    ctx.moveTo(offset, size)
    ctx.lineTo(offset + size, 0)
  }
  ctx.stroke()
  return ctx.getImageData(0, 0, size, size)
}

/** Add (once) or update the hatched layer, and show or hide it. */
export function syncUnscored(
  map: MapLibreMap,
  data: UnscoredAreaCollection,
  visible: boolean,
): void {
  if (!map.hasImage(IMAGE)) map.addImage(IMAGE, hatchImage(HATCH.size))
  const source = map.getSource(SOURCE) as GeoJSONSource | undefined
  if (source) {
    source.setData(data as unknown as GeoJSON.FeatureCollection)
  } else {
    map.addSource(SOURCE, { type: 'geojson', data: data as unknown as GeoJSON.FeatureCollection })
    map.addLayer({
      id: FILL,
      type: 'fill',
      source: SOURCE,
      paint: { 'fill-pattern': IMAGE, 'fill-opacity': 0.9 },
    })
    map.addLayer({
      id: LINE,
      type: 'line',
      source: SOURCE,
      paint: { 'line-color': HATCH.line, 'line-width': 1 },
    })
  }
  for (const id of [FILL, LINE]) {
    map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none')
  }
}
