// The deck.gl classes the features build their layers with. Loaded on demand (see deck.ts) in
// the map's chunk group, so deck.gl and luma.gl stay out of the entry bundle.
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
