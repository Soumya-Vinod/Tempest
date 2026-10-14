import type { Map as MapLibreMap } from 'maplibre-gl'

import { NEUTRAL } from './tokens'

/** Place labels of the Positron basemap (towns, villages, cities). */
const PLACE_LABELS = ['label_city_capital', 'label_city', 'label_town', 'label_village', 'label_other']

/**
 * A quieter basemap with legible place names: labels in the ink colour with a wider white halo,
 * so they still read through the translucent road network drawn over them.
 */
export function calmBasemap(map: MapLibreMap): void {
  const [r, g, b] = NEUTRAL.ink
  for (const id of PLACE_LABELS) {
    if (!map.getLayer(id)) continue
    map.setPaintProperty(id, 'text-color', `rgb(${r}, ${g}, ${b})`)
    map.setPaintProperty(id, 'text-halo-color', 'rgba(255, 255, 255, 0.95)')
    map.setPaintProperty(id, 'text-halo-width', 1.75)
    map.setPaintProperty(id, 'text-halo-blur', 0.5)
  }
}
