// The phone bottom sheet (the side panel below 768 px): three snap points and a drag handle.
// Its height is the CSS variable --sheet-h on the root element, which the sheet, the timeline,
// the legend and the cards all use (lib/layout.ts above()), so they move together; a drag
// updates only the variable. data-sheet on the root names the snap point for CSS.
import {
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  type RefObject,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'

import { type Layout, SHEET_PEEK_PX } from './layout'

export type SheetSnap = 'peek' | 'half' | 'full'
const SNAPS: readonly SheetSnap[] = ['peek', 'half', 'full']
/** A pointer that moves less than this is a tap on the handle, not a drag. */
const DRAG_SLOP_PX = 6

/** Full: up to just below the timeline, which stays above the sheet (under the KPI strip). */
const fullTop = (layout: Layout) => layout.belowKpi + layout.timelineHeight + layout.gap

/** The sheet's height at a snap point as CSS (% of the app's full-height container). */
function snapCss(snap: SheetSnap, layout: Layout): string {
  if (snap === 'peek') return `${SHEET_PEEK_PX}px`
  if (snap === 'half') return '50%'
  return `calc(100% - ${fullTop(layout)}px)`
}

function snapPx(snap: SheetSnap, layout: Layout, containerPx: number): number {
  if (snap === 'peek') return SHEET_PEEK_PX
  if (snap === 'half') return containerPx / 2
  return containerPx - fullTop(layout)
}

export interface Sheet {
  snap: SheetSnap
  /** Spread on the drag handle (a button: click or Enter cycles, arrow keys step). */
  handle: {
    onPointerDown: (e: PointerEvent<HTMLElement>) => void
    onPointerMove: (e: PointerEvent<HTMLElement>) => void
    onPointerUp: (e: PointerEvent<HTMLElement>) => void
    onPointerCancel: (e: PointerEvent<HTMLElement>) => void
    onClick: () => void
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => void
  }
  /** On the sheet: choosing a tab while it peeks opens it to half. */
  onClickCapture: (e: MouseEvent<HTMLElement>) => void
}

/**
 * Bottom-sheet state for the panel element `ref`, when `enabled` (the phone layout). It snaps
 * back to peek whenever `collapse` turns true (a card opened on the map, which it would cover).
 */
export function useSheet(
  ref: RefObject<HTMLElement | null>,
  layout: Layout,
  enabled: boolean,
  collapse: boolean,
): Sheet {
  const [snap, setSnap] = useState<SheetSnap>('peek')
  const [lastCollapse, setLastCollapse] = useState(collapse)
  if (collapse !== lastCollapse) {
    setLastCollapse(collapse)
    if (collapse) setSnap('peek')
  }

  // The variable follows the snap point (and the layout, which sets the full height).
  useLayoutEffect(() => {
    const root = document.documentElement
    if (!enabled) return
    root.style.setProperty('--sheet-h', snapCss(snap, layout))
    root.dataset.sheet = snap
    return () => {
      root.style.removeProperty('--sheet-h')
      delete root.dataset.sheet
    }
  }, [enabled, snap, layout])

  const drag = useRef<{ startY: number; startPx: number; moved: boolean } | null>(null)
  // The click that ends a drag is not a tap.
  const dragged = useRef(false)
  useEffect(() => () => void delete document.documentElement.dataset.sheetDrag, [])

  const step = (by: 1 | -1) =>
    setSnap((s) => SNAPS[Math.min(SNAPS.length - 1, Math.max(0, SNAPS.indexOf(s) + by))])

  const end = (e: PointerEvent<HTMLElement>, cancelled: boolean) => {
    const d = drag.current
    drag.current = null
    const root = document.documentElement
    delete root.dataset.sheetDrag
    if (!d?.moved) return
    dragged.current = true
    const el = ref.current
    const container = el?.parentElement?.clientHeight ?? window.innerHeight
    const height = cancelled || !el ? d.startPx : el.getBoundingClientRect().height
    const nearest = SNAPS.reduce((a, b) =>
      Math.abs(snapPx(b, layout, container) - height) < Math.abs(snapPx(a, layout, container) - height) ? b : a,
    )
    // Set the variable here too: the effect won't run if the snap point is unchanged.
    root.style.setProperty('--sheet-h', snapCss(nearest, layout))
    setSnap(nearest)
    e.currentTarget.releasePointerCapture(e.pointerId)
  }

  return {
    snap,
    handle: {
      onPointerDown: (e) => {
        if (!ref.current) return
        drag.current = { startY: e.clientY, startPx: ref.current.getBoundingClientRect().height, moved: false }
        dragged.current = false
        e.currentTarget.setPointerCapture(e.pointerId)
      },
      onPointerMove: (e) => {
        const d = drag.current
        if (!d) return
        const dy = e.clientY - d.startY
        if (!d.moved && Math.abs(dy) < DRAG_SLOP_PX) return
        d.moved = true
        const container = ref.current?.parentElement?.clientHeight ?? window.innerHeight
        const max = snapPx('full', layout, container)
        const root = document.documentElement
        root.dataset.sheetDrag = ''
        root.style.setProperty('--sheet-h', `${Math.min(max, Math.max(SHEET_PEEK_PX, d.startPx - dy))}px`)
      },
      onPointerUp: (e) => end(e, false),
      onPointerCancel: (e) => end(e, true),
      onClick: () => {
        if (dragged.current) {
          dragged.current = false
          return
        }
        setSnap((s) => (s === 'peek' ? 'half' : s === 'half' ? 'full' : 'peek'))
      },
      onKeyDown: (e) => {
        if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
        e.preventDefault()
        step(e.key === 'ArrowUp' ? 1 : -1)
      },
    },
    onClickCapture: (e) => {
      if (snap === 'peek' && (e.target as Element).closest('[role="tab"]')) setSnap('half')
    },
  }
}
