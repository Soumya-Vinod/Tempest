import { type ComponentProps, lazy, Suspense, useState } from 'react'

import { loadDeck } from '../lib/deck'
import { PANEL_WIDTH, UI_GAP } from '../lib/layout'
import type MapViewComponent from './MapView'

type Props = ComponentProps<typeof MapViewComponent>

// MapLibre, deck.gl and luma.gl are most of the app's JavaScript: they load in their own chunks,
// after the shell. The map shows once both MapView and the deck.gl layer classes are in (the
// features build no layers before that). A failed load is forgotten, so a remount tries again.
let pending: Promise<{ default: typeof MapViewComponent }> | null = null
function loadMapView() {
  pending ??= Promise.all([import('./MapView'), loadDeck()]).then(
    ([m]) => m,
    (err: unknown) => {
      pending = null
      throw err
    },
  )
  return pending
}

/**
 * The map, code-split. It is in the first render, so its chunks start loading as soon as the
 * shell renders, with no interaction needed; the panels and timeline are usable meanwhile. A
 * failed load throws to MapErrorBoundary. Its remount gets a fresh lazy component (React.lazy
 * keeps a failure for good); a failed download, which browsers cache, offers a page reload.
 */
export default function LazyMapView(props: Props) {
  const [MapView] = useState(() => lazy(loadMapView))
  return (
    <Suspense fallback={<MapPlaceholder />}>
      <MapView {...props} />
    </Suspense>
  )
}

function MapPlaceholder() {
  return (
    <div
      className="absolute inset-0 flex items-center justify-center bg-slate-100 text-sm text-slate-500"
      style={{ paddingRight: PANEL_WIDTH + 2 * UI_GAP }}
      role="status"
    >
      Loading map…
    </div>
  )
}
