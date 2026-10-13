import { useState } from 'react'

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
 * Key moments above the track, click to jump. Quiet by default: a caption only on landfall and on
 * the hovered, focused or current marker; the full label is always in the tooltip. On phones the
 * caption is only the time (the bar is too narrow).
 */
export default function Markers({
  moments,
  onJump,
  current,
}: {
  moments: KeyMoment[]
  onJump: (index: number) => void
  /** The scrubber's timestep index: its marker, if any, is captioned. */
  current: number
}) {
  const timeline = useTimeline()
  const { landfallIndex } = timeline
  const { phone } = useLayout()
  const [hovered, setHovered] = useState<number | null>(null)
  return (
    <div className="relative h-7" aria-label="Key moments">
      {groups(moments, timeline.indexOf).map(({ index, moments: ms }) => {
        const at = timeline.label(index)
        const caption = ms.map((m) => MOMENT[m.kind].caption).join(' & ')
        const full = `${ms.map((m) => m.label).join('; ')} (${at})`
        const fraction = index / landfallIndex
        const captioned = index === landfallIndex || index === hovered || index === current
        // Keep the caption inside the bar at both ends.
        const align = fraction > 0.85 ? '-translate-x-full' : fraction < 0.15 ? '' : '-translate-x-1/2'
        return (
          <button
            key={index}
            type="button"
            onClick={() => onJump(index)}
            onMouseEnter={() => setHovered(index)}
            onMouseLeave={() => setHovered(null)}
            onFocus={() => setHovered(index)}
            onBlur={() => setHovered(null)}
            aria-label={`${full}. Jump to ${at}.`}
            title={full}
            className="absolute top-0 flex h-7 flex-col items-center rounded-sm"
            style={{ left: trackLeft(fraction), transform: 'translateX(-50%)' }}
          >
            {captioned && (
              <span
                className={`pointer-events-none absolute top-0 left-1/2 text-[11px] leading-3 whitespace-nowrap text-ink-muted ${align}`}
                style={align === '' ? { left: 0 } : align === '-translate-x-full' ? { left: '100%' } : undefined}
              >
                {phone ? at : `${caption} · ${at}`}
              </span>
            )}
            <span
              className="mt-3.5 block size-2.5 rotate-45 ring-1 ring-white"
              style={{ background: fill(ms.map((m) => m.kind)) }}
              aria-hidden
            />
          </button>
        )
      })}
    </div>
  )
}
