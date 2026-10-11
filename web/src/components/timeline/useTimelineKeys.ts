import { useEffect } from 'react'

/**
 * Timeline keys anywhere on the page: ←/→ step, Space play/pause, Home/End first/last step. Not
 * while typing, on the map (its own arrow-key panning), on tabs (arrows move between tabs), on the
 * range (native arrows/Home/End already step it), or with a modifier held.
 */
export function useTimelineKeys(actions: {
  step: (delta: number) => void
  first: () => void
  last: () => void
  togglePlay: () => void
}) {
  const { step, first, last, togglePlay } = actions
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return
      const t = e.target instanceof HTMLElement ? e.target : null
      const tag = t?.tagName ?? ''
      const isRange = tag === 'INPUT' && (t as HTMLInputElement).type === 'range'
      const typing = !!t && (t.isContentEditable || tag === 'TEXTAREA' || tag === 'SELECT' || (tag === 'INPUT' && !isRange))
      if (typing || t?.closest('.maplibregl-map') || t?.getAttribute('role') === 'tab') return
      const clickable = tag === 'BUTTON' || tag === 'A' || tag === 'SUMMARY'
      if (e.key === ' ' && !clickable) togglePlay()
      else if (isRange) return
      else if (e.key === 'ArrowLeft') step(-1)
      else if (e.key === 'ArrowRight') step(1)
      else if (e.key === 'Home') first()
      else if (e.key === 'End') last()
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [step, first, last, togglePlay])
}
