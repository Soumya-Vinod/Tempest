import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useCountdownSeries } from '../features/countdown'
import { above, useLayout } from '../lib/layout'
import { useTimeline } from '../lib/timeline'
import { useApiStatus } from '../lib/useApiStatus'
import type { KeyMoment } from '../types/contracts'
import Markers from './timeline/Markers'
import Sparkline from './timeline/Sparkline'
import { trackLeft } from './timeline/track'
import { useTimelineKeys } from './timeline/useTimelineKeys'

interface Props {
  index: number
  onChange: (index: number) => void
  /** Key moments of the replay (v1.3, from the action countdown), marked on the track. */
  moments?: KeyMoment[]
  /** The countdown failed, so there are no key moments or sparkline (only Landfall is known). */
  markersFailed?: boolean
  /** The storm's IMD category at this timestep, shown quietly beside the time. */
  storm?: string
}

const TICK_EVERY_H = 24 // labelled ticks: T-72, T-48, T-24, T-0
const PLAY_STEP_MS = 1500
const KEYS = 'Keyboard: ← → step, Space play or pause, Home / End first or last step'
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const pad = (n: number) => String(n).padStart(2, '0')

/** "20 May, 06:00 UTC" from an ISO timestep. */
function readable(ts: string): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
}

const BUTTON =
  'rounded-control border border-line px-2 py-0.5 text-ink-muted hover:bg-surface disabled:opacity-40'

export default function TimelineScrubber({
  index,
  onChange,
  moments = [],
  markersFailed = false,
  storm,
}: Props) {
  const timeline = useTimeline()
  const { landfallIndex, label: relativeLabel } = timeline
  const timestep = timeline.timesteps[index]
  // Landfall is known from the timesteps: marked even when the countdown's moments are missing.
  const landfallAt = timeline.timesteps[landfallIndex]
  const marked = useMemo(
    () =>
      moments.some((m) => m.kind === 'landfall')
        ? moments
        : [...moments, { kind: 'landfall' as const, timestep: landfallAt, label: 'Landfall' }],
    [moments, landfallAt],
  )
  const series = useCountdownSeries(timeline.timesteps)
  const [playing, setPlaying] = useState(false)
  const { busy } = useApiStatus()
  const lastStepAt = useRef(0)
  const step = useCallback(
    (delta: number) => onChange(Math.min(landfallIndex, Math.max(0, index + delta))),
    [onChange, landfallIndex, index],
  )

  // Play: one step every PLAY_STEP_MS at most, stopping at landfall. It waits while any API
  // request is queued or in flight, so the current timestep's data has loaded before the next
  // step (never more than one timestep ahead of the data). Prefetches never count as busy.
  useEffect(() => {
    if (!playing || busy) return
    const wait = Math.max(0, PLAY_STEP_MS - (Date.now() - lastStepAt.current))
    const id = window.setTimeout(() => {
      const next = Math.min(landfallIndex, index + 1)
      lastStepAt.current = Date.now()
      onChange(next)
      if (next === landfallIndex) setPlaying(false)
    }, wait)
    return () => window.clearTimeout(id)
  }, [playing, busy, index, onChange, landfallIndex])

  const togglePlay = useCallback(() => {
    if (playing) return setPlaying(false)
    if (index === landfallIndex) onChange(0) // replay from the start
    lastStepAt.current = Date.now()
    setPlaying(true)
  }, [playing, index, landfallIndex, onChange])

  const layout = useLayout()
  const { compactTimeline, timelineHeight, gap, phone } = layout

  useTimelineKeys({
    step,
    first: useCallback(() => onChange(0), [onChange]),
    last: useCallback(() => onChange(landfallIndex), [onChange, landfallIndex]),
    togglePlay,
  })

  const sparkline = !compactTimeline && !markersFailed
  return (
    <div
      className={`absolute z-20 flex flex-col justify-center rounded-panel border border-line bg-white text-sm text-ink shadow-sm ${
        phone ? 'sheet-rides px-3' : 'px-4'
      }`}
      style={{ left: gap, right: gap, bottom: above(layout, gap), height: timelineHeight }}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => step(-1)}
          disabled={index === 0}
          className={BUTTON}
          aria-label="Previous timestep"
          aria-keyshortcuts="ArrowLeft"
        >
          ◀
        </button>
        <button
          type="button"
          onClick={() => step(1)}
          disabled={index === landfallIndex}
          className={BUTTON}
          aria-label="Next timestep"
          aria-keyshortcuts="ArrowRight"
        >
          ▶
        </button>
        <button
          type="button"
          onClick={togglePlay}
          className={`${BUTTON} text-xs`}
          aria-label={playing ? 'Pause replay' : 'Play replay'}
          aria-pressed={playing}
          aria-keyshortcuts="Space"
          title={KEYS}
        >
          {playing ? '❚❚ Pause' : '▶ Play'}
        </button>
        <span className="ml-2 text-figure font-semibold whitespace-nowrap tabular-nums">
          {relativeLabel(index)} h
        </span>
        <span className="hidden text-xs whitespace-nowrap text-ink-subtle tabular-nums sm:inline" title={timestep}>
          {readable(timestep)}
        </span>
        {index === landfallIndex && (
          <span className="rounded-full border border-line bg-surface px-2 text-[11px] whitespace-nowrap text-ink-muted">
            Landfall
          </span>
        )}
        {storm && !phone && (
          <span className="hidden truncate text-[11px] text-ink-subtle md:inline" title="IMD category at this step">
            · {storm}
          </span>
        )}
        {markersFailed && (
          <span className="ml-auto text-[11px] text-ink-subtle" role="status">
            Timeline markers unavailable
          </span>
        )}
        <div className={`flex items-center gap-3 text-[11px] whitespace-nowrap text-ink-subtle ${markersFailed ? '' : 'ml-auto'}`}>
          {sparkline && (
            <ul className="hidden items-center gap-3 lg:flex" aria-label="Timeline legend">
              <li className="flex items-center gap-1">
                <span className="block h-2 w-3 rounded-sm bg-sev-cut-wash ring-1 ring-sev-cut/60" aria-hidden />
                Cut off
              </li>
              <li className="flex items-center gap-1">
                <span className="block w-3 border-t border-dashed border-sev-act" aria-hidden />
                Expected
              </li>
            </ul>
          )}
          <span className="cursor-help rounded-full border border-line px-1.5 leading-4" title={KEYS} role="note" aria-label={KEYS}>
            Keys
          </span>
        </div>
      </div>
      <Markers moments={marked} onJump={onChange} current={index} />
      <div className="relative">
        {sparkline && <Sparkline points={series} labelOf={relativeLabel} />}
        <input
          type="range"
          min={0}
          max={landfallIndex}
          step={1}
          value={index}
          onChange={(e) => onChange(Number(e.target.value))}
          className={`timeline-range relative w-full ${compactTimeline ? '' : '-mt-2'}`}
          style={{ '--pct': `${(index / Math.max(1, landfallIndex)) * 100}%` } as CSSProperties}
          aria-label="Replay timestep"
          aria-valuetext={`${relativeLabel(index)} hours, ${timestep}`}
        />
      </div>
      {/* A tick per step; taller every 24 h, which are labelled below. */}
      <div className="relative h-1.5" aria-hidden>
        {timeline.timesteps.map((_, i) => {
          const major = timeline.hoursToLandfall(i) % TICK_EVERY_H === 0
          return (
            <span
              key={i}
              className={`absolute top-0 w-px -translate-x-1/2 ${major ? 'h-1.5 bg-ink-subtle/60' : 'h-1 bg-line'}`}
              style={{ left: trackLeft(i / landfallIndex) }}
            />
          )
        })}
      </div>
      {!compactTimeline && (
        <div className="flex justify-between text-[11px] text-ink-subtle">
          {timeline.timesteps.flatMap((_, i) =>
            timeline.hoursToLandfall(i) % TICK_EVERY_H === 0
              ? [<span key={i}>{i === landfallIndex ? 'T-0 landfall' : relativeLabel(i)}</span>]
              : [],
          )}
        </div>
      )}
    </div>
  )
}
