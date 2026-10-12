import { useEffect, useRef, useState } from 'react'

import { TIMELINE_HEIGHT, UI_GAP } from '../lib/layout'
import { useTimeline } from '../lib/timeline'
import { useApiStatus } from '../lib/useApiStatus'
import type { KeyMoment, KeyMomentKind } from '../types/contracts'

interface Props {
  index: number
  onChange: (index: number) => void
  /** Key moments of the replay (v1.3, from the action countdown), marked on the track. */
  moments?: KeyMoment[]
}

const TICK_EVERY_H = 24 // labelled ticks: T-72, T-48, T-24, T-0
const PLAY_STEP_MS = 1500
const THUMB_PX = 16 // the range thumb's width: markers line up with its centre

const MOMENT_COLOR: Record<KeyMomentKind, string> = {
  first_alert: 'bg-amber-500',
  first_expected_isolation: 'bg-violet-500',
  first_actual_isolation: 'bg-red-900',
  landfall: 'bg-slate-800',
}

function MomentMarker({
  moment,
  index,
  onJump,
}: {
  moment: KeyMoment
  index: number
  onJump: (index: number) => void
}) {
  const { label: at, landfallIndex } = useTimeline()
  const label = `${moment.label} (${at(index)})`
  return (
    <button
      type="button"
      onClick={() => onJump(index)}
      aria-label={label}
      className="group absolute top-0 -translate-x-1/2"
      style={{
        left: `calc(${THUMB_PX / 2}px + (100% - ${THUMB_PX}px) * ${index / landfallIndex})`,
      }}
    >
      <span className={`block size-2.5 rotate-45 ${MOMENT_COLOR[moment.kind]}`} />
      <span className="pointer-events-none absolute bottom-full left-1/2 mb-1 hidden -translate-x-1/2 rounded bg-slate-800 px-1.5 py-0.5 text-[11px] whitespace-nowrap text-white group-hover:block group-focus-visible:block">
        {label}
      </span>
    </button>
  )
}

export default function TimelineScrubber({ index, onChange, moments = [] }: Props) {
  const timeline = useTimeline()
  const { landfallIndex, label: relativeLabel } = timeline
  const timestep = timeline.timesteps[index]
  const ticks = timeline.timesteps.flatMap((_, i) =>
    timeline.hoursToLandfall(i) % TICK_EVERY_H === 0 ? [i] : [],
  )
  const [playing, setPlaying] = useState(false)
  const { busy } = useApiStatus()
  const lastStepAt = useRef(0)
  const step = (delta: number) =>
    onChange(Math.min(landfallIndex, Math.max(0, index + delta)))

  // Play: one step every PLAY_STEP_MS at most, stopping at landfall. It waits while any API
  // request is queued or in flight, so the current timestep's data has loaded before the next
  // step (never more than one timestep ahead of the data).
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

  const togglePlay = () => {
    if (playing) return setPlaying(false)
    if (index === landfallIndex) onChange(0) // replay from the start
    lastStepAt.current = Date.now()
    setPlaying(true)
  }

  const placed = moments.flatMap((m) => {
    const i = timeline.indexOf(m.timestep)
    return i >= 0 ? [{ moment: m, index: i }] : []
  })

  return (
    <div
      className="absolute z-20 flex flex-col justify-center rounded-lg bg-white px-4 text-sm text-slate-800 shadow-lg"
      style={{ left: UI_GAP, right: UI_GAP, bottom: UI_GAP, height: TIMELINE_HEIGHT }}
    >
      <div className="mb-1 flex items-center gap-3">
        <button
          type="button"
          onClick={() => step(-1)}
          disabled={index === 0}
          className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40"
          aria-label="Previous timestep"
        >
          ◀
        </button>
        <button
          type="button"
          onClick={() => step(1)}
          disabled={index === landfallIndex}
          className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40"
          aria-label="Next timestep"
        >
          ▶
        </button>
        <button
          type="button"
          onClick={togglePlay}
          className="rounded border border-slate-300 px-2 py-0.5 text-xs"
          aria-label={playing ? 'Pause replay' : 'Play replay'}
          aria-pressed={playing}
        >
          {playing ? '❚❚ Pause' : '▶ Play'}
        </button>
        <span className="font-semibold">{relativeLabel(index)}h</span>
        <span className="font-mono text-xs text-slate-600">{timestep}</span>
        {index === landfallIndex && (
          <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800">
            LANDFALL
          </span>
        )}
      </div>
      <div className="relative h-3" aria-label="Key moments">
        {placed.map(({ moment, index: i }) => (
          <MomentMarker key={moment.kind} moment={moment} index={i} onJump={onChange} />
        ))}
      </div>
      <input
        type="range"
        min={0}
        max={landfallIndex}
        step={1}
        value={index}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-slate-800"
        aria-label="Replay timestep"
        aria-valuetext={`${relativeLabel(index)} hours, ${timestep}`}
      />
      <div className="flex justify-between text-xs text-slate-500">
        {ticks.map((i) => (
          <span key={i}>{i === landfallIndex ? 'T-0 landfall' : relativeLabel(i)}</span>
        ))}
      </div>
    </div>
  )
}
