import { useCallback, useEffect, useRef, useState } from 'react'

import { useCountdownSeries } from '../features/countdown'
import { above, useLayout } from '../lib/layout'
import { useTimeline } from '../lib/timeline'
import { useApiStatus } from '../lib/useApiStatus'
import type { KeyMoment } from '../types/contracts'
import Markers from './timeline/Markers'
import { MOMENT, MOMENT_ORDER } from './timeline/moments'
import Sparkline from './timeline/Sparkline'
import { trackLeft } from './timeline/track'
import { useTimelineKeys } from './timeline/useTimelineKeys'

interface Props {
  index: number
  onChange: (index: number) => void
  /** Key moments of the replay (v1.3, from the action countdown), marked on the track. */
  moments?: KeyMoment[]
}

const TICK_EVERY_H = 24 // labelled ticks: T-72, T-48, T-24, T-0
const PLAY_STEP_MS = 1500

export default function TimelineScrubber({ index, onChange, moments = [] }: Props) {
  const timeline = useTimeline()
  const { landfallIndex, label: relativeLabel } = timeline
  const timestep = timeline.timesteps[index]
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

  return (
    <div
      className={`absolute z-20 flex flex-col justify-center rounded-lg bg-white text-sm text-slate-800 shadow-lg ${
        phone ? 'sheet-rides px-3' : 'px-4'
      }`}
      style={{ left: gap, right: gap, bottom: above(layout, gap), height: timelineHeight }}
    >
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => step(-1)}
          disabled={index === 0}
          className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40"
          aria-label="Previous timestep"
          aria-keyshortcuts="ArrowLeft"
        >
          ◀
        </button>
        <button
          type="button"
          onClick={() => step(1)}
          disabled={index === landfallIndex}
          className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40"
          aria-label="Next timestep"
          aria-keyshortcuts="ArrowRight"
        >
          ▶
        </button>
        <button
          type="button"
          onClick={togglePlay}
          className="rounded border border-slate-300 px-2 py-0.5 text-xs"
          aria-label={playing ? 'Pause replay' : 'Play replay'}
          aria-pressed={playing}
          aria-keyshortcuts="Space"
        >
          {playing ? '❚❚ Pause' : '▶ Play'}
        </button>
        <span className="font-semibold whitespace-nowrap">{relativeLabel(index)}h</span>
        <span className="hidden font-mono text-xs text-slate-600 sm:inline">{timestep}</span>
        {index === landfallIndex && (
          <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800">
            LANDFALL
          </span>
        )}
        <ul className="ml-auto hidden items-center gap-3 text-[10px] whitespace-nowrap text-slate-500 xl:flex" aria-label="Timeline legend">
          {MOMENT_ORDER.map((k) => (
            <li key={k} className="flex items-center gap-1">
              <span className="block size-2 rotate-45" style={{ background: MOMENT[k].color }} aria-hidden />
              {MOMENT[k].legend}
            </li>
          ))}
          <li className="flex items-center gap-1">
            <span className="block h-2 w-3 rounded-sm bg-red-900/25 ring-1 ring-red-900/70" aria-hidden />
            Cut off
          </li>
          <li className="flex items-center gap-1">
            <span className="block w-3 border-t border-dashed border-amber-600" aria-hidden />
            Expected
          </li>
          <li className="text-slate-400">← → step · Space play · Home/End</li>
        </ul>
      </div>
      <Markers moments={moments} onJump={onChange} />
      <div className="relative">
        {!compactTimeline && <Sparkline points={series} labelOf={relativeLabel} />}
        <input
          type="range"
          min={0}
          max={landfallIndex}
          step={1}
          value={index}
          onChange={(e) => onChange(Number(e.target.value))}
          className={`relative w-full accent-slate-800 ${compactTimeline ? '' : '-mt-2'}`}
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
              className={`absolute top-0 w-px -translate-x-1/2 ${major ? 'h-1.5 bg-slate-500' : 'h-1 bg-slate-300'}`}
              style={{ left: trackLeft(i / landfallIndex) }}
            />
          )
        })}
      </div>
      {!compactTimeline && (
        <div className="flex justify-between text-xs text-slate-500">
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
