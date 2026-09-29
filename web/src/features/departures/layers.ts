import type { Layer } from '@deck.gl/core'
import { PathStyleExtension, type PathStyleExtensionProps } from '@deck.gl/extensions'
import { PathLayer } from '@deck.gl/layers'

import type { Departure, DepartureLeg } from '../../types/contracts'

const ROUTE_COLOR: [number, number, number] = [8, 145, 178] // cyan-600

/** The selected facility's departure route: solid by road, dashed by ferry. */
export function buildRouteLayers(departure: Departure | null): Layer[] {
  const legs = departure?.legs ?? []
  if (legs.length === 0) return []
  return [
    new PathLayer<DepartureLeg, PathStyleExtensionProps<DepartureLeg>>({
      id: 'departure-route',
      data: legs,
      getPath: (d) => d.geometry.coordinates as [number, number][],
      getColor: ROUTE_COLOR,
      widthUnits: 'pixels',
      getWidth: 4,
      capRounded: true,
      jointRounded: true,
      getDashArray: (d) => (d.ferry ? [4, 3] : [0, 0]),
      dashJustified: true,
      extensions: [new PathStyleExtension({ dash: true })],
    }),
  ]
}
