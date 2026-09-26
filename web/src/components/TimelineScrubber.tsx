import { LANDFALL_INDEX, REPLAY_TIMESTEPS, relativeLabel } from '../lib/constants'
import { TIMELINE_HEIGHT, UI_GAP } from '../lib/layout'

interface Props {
  index: number
  onChange: (index: number) => void
}

const TICKS = [0, 8, 16, LANDFALL_INDEX] // T-72, T-48, T-24, T-0

export default function TimelineScrubber({ index, onChange }: Props) {
  const timestep = REPLAY_TIMESTEPS[index]
  const step = (delta: number) =>
    onChange(Math.min(LANDFALL_INDEX, Math.max(0, index + delta)))

  return (
    <div
      className="absolute z-20 flex flex-col justify-center rounded-lg bg-white px-4 text-sm text-slate-800 shadow-lg"
      style={{ left: UI_GAP, right: UI_GAP, bottom: UI_GAP, height: TIMELINE_HEIGHT }}
    >
      <div className="mb-2 flex items-center gap-3">
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
          disabled={index === LANDFALL_INDEX}
          className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40"
          aria-label="Next timestep"
        >
          ▶
        </button>
        <span className="font-semibold">{relativeLabel(index)}h</span>
        <span className="font-mono text-xs text-slate-600">{timestep}</span>
        {index === LANDFALL_INDEX && (
          <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800">
            LANDFALL
          </span>
        )}
      </div>
      <input
        type="range"
        min={0}
        max={LANDFALL_INDEX}
        step={1}
        value={index}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-slate-800"
        aria-label="Replay timestep"
        aria-valuetext={`${relativeLabel(index)} hours, ${timestep}`}
      />
      <div className="flex justify-between text-xs text-slate-500">
        {TICKS.map((i) => (
          <span key={i}>{i === LANDFALL_INDEX ? 'T-0 landfall' : relativeLabel(i)}</span>
        ))}
      </div>
    </div>
  )
}
