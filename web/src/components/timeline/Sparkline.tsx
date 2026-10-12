import type { CountdownPoint } from '../../features/countdown'
import { THUMB_PX } from './track'

const H = 22

/**
 * Facilities cut off (filled) and expected to be cut off within 24 h (line) at every step, drawn
 * along the track behind the thumb. Loaded points only; gaps stay gaps.
 */
export default function Sparkline({ points, labelOf }: { points: CountdownPoint[]; labelOf: (i: number) => string }) {
  const n = points.length
  const loaded = points.flatMap((p, i) => (p ? [{ ...p, i }] : []))
  if (n < 2 || loaded.length === 0) return <div style={{ height: H }} aria-hidden />
  const max = Math.max(1, ...loaded.map((p) => Math.max(p.cutOff, p.expected)))
  const x = (i: number) => (i / (n - 1)) * 1000
  const y = (v: number) => H - 1 - (v / max) * (H - 3)
  const area = `M${x(loaded[0].i)},${H} ${loaded.map((p) => `L${x(p.i)},${y(p.cutOff)}`).join(' ')} L${x(loaded[loaded.length - 1].i)},${H} Z`
  const line = loaded.map((p, k) => `${k ? 'L' : 'M'}${x(p.i)},${y(p.expected)}`).join(' ')
  const peak = loaded.reduce((a, b) => (b.cutOff > a.cutOff ? b : a))
  const summary = `Facilities cut off per step, peak ${peak.cutOff} at ${labelOf(peak.i)}; dashed: expected to be cut off within 24 h.`
  return (
    <div style={{ height: H, paddingLeft: THUMB_PX / 2, paddingRight: THUMB_PX / 2 }} title={summary}>
      <svg viewBox={`0 0 1000 ${H}`} preserveAspectRatio="none" className="h-full w-full" role="img" aria-label={summary}>
        <path d={area} fill="rgb(127 29 29 / 0.22)" stroke="rgb(127 29 29 / 0.8)" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
        <path d={line} fill="none" stroke="rgb(127 29 29)" strokeWidth="1.2" strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  )
}
