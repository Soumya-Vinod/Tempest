/** Contract AOI (contracts.md §1): South 24 Parganas / Sundarbans, EPSG:4326. */
export const AOI_BBOX: [minLon: number, minLat: number, maxLon: number, maxLat: number] = [
  88.0, 21.5, 89.1, 22.7,
]

/** OpenFreeMap Positron: free, keyless vector basemap. */
export const BASEMAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'

/**
 * The map switches from the Hazard to the Risk view (until the user picks one) once any block
 * scores this much: the advisory suggestion threshold (api/app/advisory/service.py).
 */
export const RISK_VIEW_MIN_SCORE = 0.25
