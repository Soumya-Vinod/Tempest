import { useLayout } from '../../lib/layout'
import { useTimeline } from '../../lib/timeline'
import type { KeyMoment, KeyMomentKind } from '../../types/contracts'
import { MOMENT, MOMENT_ORDER as ORDER } from './moments'
import { trackLeft } from './track'

interface Group {
  index: number
  moments: KeyMoment[]
}

/** Moments on the same timestep become one marker (e.g. first alert and first expected cut-off). */
function groups(moments: KeyMoment[], indexOf: (ts: string | null) => number): Group[] {
  const by = new Map<number, KeyMoment[]>()
  for (const m of moments) {
    const i = indexOf(m.timestep)
    if (i < 0) continue
    by.set(i, [...(by.get(i) ?? []), m])
  }
  return [...by.entries()]
    .sort(([a], [b]) => a - b)
    .map(([index, ms]) => ({ index, moments: ms.sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind)) }))
}

/** A diamond split diagonally between the merged moments' colours. */
function fill(kinds: KeyMomentKind[]): string {
  if (kinds.length === 1) return MOMENT[kinds[0]].color
  const step = 100 / kinds.length
  const stops = kinds.map((k, i) => `${MOMENT[k].color} ${i * step}% ${(i + 1) * step}%`)
  return `linear-gradient(90deg, ${stops.join(', ')})`
}

/**
 * Key moments above the track: a captioned marker each (merged per timestep), click to jump. On
 * phones the caption is only the time (the bar is too narrow); the full one is in the tooltip.
 */
export default function Markers({ moments, onJump }: { moments: KeyMoment[]; onJump: (index: number) => void }) {
  const timeline = useTimeline()
  const { landfallIndex } = timeline
  const { phone } = useLayout()
  return (
    <div className="relative h-7" aria-label="Key moments">
      {groups(moments, timeline.indexOf).map(({ index, moments: ms }) => {
        const at = timeline.label(index)
        const caption = ms.map((m) => MOMENT[m.kind].caption).join(' & ')
        const full = `${ms.map((m) => m.label).join('; ')} (${at})`
        const fraction = index / landfallIndex
        // Keep the caption inside the bar at both ends.
        const align = fraction > 0.85 ? '-translate-x-full' : fraction < 0.15 ? '' : '-translate-x-1/2'
        return (
          <button
            key={index}
            type="button"
            onClick={() => onJump(index)}
            aria-label={`${full}. Jump to ${at}.`}
            title={full}
            className="absolute top-0 flex h-7 flex-col items-center"
            style={{ left: trackLeft(fraction), transform: 'translateX(-50%)' }}
          >
            <span
              className={`pointer-events-none absolute top-0 left-1/2 text-[10px] leading-3 font-medium whitespace-nowrap text-slate-700 ${align}`}
              style={align === '' ? { left: 0 } : align === '-translate-x-full' ? { left: '100%' } : undefined}
            >
              {phone ? at : `${caption} · ${at}`}
            </span>
            <span
              className="mt-3.5 block size-3 rotate-45 ring-1 ring-white"
              style={{ background: fill(ms.map((m) => m.kind)) }}
              aria-hidden
            />
          </button>
        )
      })}
    </div>
  )
}
