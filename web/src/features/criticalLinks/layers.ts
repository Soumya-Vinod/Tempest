import type { Layer } from '@deck.gl/core'
import { PathStyleExtension, type PathStyleExtensionProps } from '@deck.gl/extensions'
import { PathLayer } from '@deck.gl/layers'

import type { CriticalLink } from '../../types/contracts'

const LINK_COLOR: [number, number, number] = [217, 119, 6] // amber-600
const CASING: [number, number, number] = [255, 255, 255]

interface Path {
  path: [number, number][]
  ferry: boolean
}

function paths(link: CriticalLink): Path[] {
  const g = link.geometry
  const lines = g.type === 'LineString' ? [g.coordinates] : g.coordinates
  return lines.map((c) => ({ path: c as [number, number][], ferry: link.link_type === 'ferry' }))
}

/** The hovered or clicked critical links (v1.4): amber on a white casing, dashed for a ferry. */
export function buildLinkLayers(links: CriticalLink[]): Layer[] {
  if (links.length === 0) return []
  const data = links.flatMap(paths)
  return [
    new PathLayer<Path>({
      id: 'critical-link-casing',
      data,
      getPath: (d) => d.path,
      getColor: CASING,
      widthUnits: 'pixels',
      getWidth: 9,
      capRounded: true,
      jointRounded: true,
    }),
    new PathLayer<Path, PathStyleExtensionProps<Path>>({
      id: 'critical-link',
      data,
      getPath: (d) => d.path,
      getColor: LINK_COLOR,
      widthUnits: 'pixels',
      getWidth: 5,
      capRounded: true,
      jointRounded: true,
      getDashArray: (d) => (d.ferry ? [4, 3] : [0, 0]),
      dashJustified: true,
      extensions: [new PathStyleExtension({ dash: true })],
    }),
  ]
}
