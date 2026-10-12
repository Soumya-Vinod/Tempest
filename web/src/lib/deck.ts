import { useSyncExternalStore } from 'react'

/** The deck.gl layer and extension classes (deckLayers.ts), loaded with the map. */
export type Deck = typeof import('./deckLayers')

let deck: Deck | null = null
let loading: Promise<Deck> | null = null
const listeners = new Set<() => void>()

/**
 * Starts loading the deck.gl classes (once) and resolves when they're ready. A failed load is
 * forgotten, so the next call (e.g. "Reload map") tries again.
 */
export function loadDeck(): Promise<Deck> {
  loading ??= import('./deckLayers').then(
    (m) => {
      deck = m
      for (const l of listeners) l()
      return m
    },
    (err: unknown) => {
      loading = null
      throw err
    },
  )
  return loading
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  // A failure surfaces through the map's own load (LazyMapView), not here.
  loadDeck().catch(() => {})
  return () => void listeners.delete(listener)
}

/**
 * The deck.gl classes once loaded (the first use starts loading them), else null: build no
 * layers yet (the map, which needs them too, isn't up either).
 */
export function useDeck(): Deck | null {
  return useSyncExternalStore(subscribe, () => deck)
}
