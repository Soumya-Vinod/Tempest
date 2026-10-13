// The deck.gl classes the features build their layers with. Loaded on demand (see deck.ts) in
// the map's chunk group, so deck.gl and luma.gl stay out of the entry bundle.
import { log as lumaLog } from '@luma.gl/core'

// Production only: luma.gl logs a benign note at level 0 for every shader ("WebGL uniform block
// reflection failed …; using supplied std140 metadata"). Below level 0 its console output stays
// quiet; thrown errors still reach the map's error boundary. Development keeps every message.
if (import.meta.env.PROD) lumaLog.setLevel(-1)

export { MaskExtension, PathStyleExtension } from '@deck.gl/extensions'
export {
  BitmapLayer,
  GeoJsonLayer,
  IconLayer,
  PathLayer,
  PolygonLayer,
  ScatterplotLayer,
  TextLayer,
} from '@deck.gl/layers'
