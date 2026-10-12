import type { Sheet, SheetSnap } from '../lib/sheet'

const SIZE: Record<SheetSnap, string> = {
  peek: 'tabs only',
  half: 'half screen',
  full: 'full screen',
}

/** The phone sheet's grab bar: drag it, tap it (peek → half → full → peek), or use ↑ / ↓. */
export default function SheetHandle({ snap, handle }: Pick<Sheet, 'snap' | 'handle'>) {
  return (
    <button
      type="button"
      {...handle}
      aria-label={`Panel size: ${SIZE[snap]}. Drag, tap or use the up and down arrow keys to resize.`}
      aria-expanded={snap !== 'peek'}
      aria-keyshortcuts="ArrowUp ArrowDown"
      className="flex h-6 w-full shrink-0 cursor-grab touch-none items-center justify-center active:cursor-grabbing"
    >
      <span className="h-1.5 w-12 rounded-full bg-slate-300" aria-hidden />
    </button>
  )
}
