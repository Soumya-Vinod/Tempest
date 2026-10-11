import type { ImpactStatus } from '../../types/contracts'
import { cssColor, IMPACT_COLOR } from './style'

const ISOLATED = cssColor(IMPACT_COLOR.isolated)

/**
 * A status as the map draws it (16 px): isolated is a target in a halo, expected isolation the
 * same ring dashed, cut a red line with a dot, at risk a thin amber line, OK a grey dot. Shape
 * and colour both differ, so it reads without colour.
 */
export default function StatusSwatch({
  status,
  expected = false,
}: {
  status: ImpactStatus
  /** Isolated status expected within 24 h, not yet: the dashed ring. */
  expected?: boolean
}) {
  return (
    <svg viewBox="0 0 16 16" className="size-4 shrink-0" aria-hidden>
      {status === 'isolated' && expected && (
        <circle cx="8" cy="8" r="5.5" fill="white" stroke={ISOLATED} strokeWidth="2" strokeDasharray="2.6 1.8" />
      )}
      {status === 'isolated' && !expected && (
        <>
          <circle cx="8" cy="8" r="8" fill={ISOLATED} fillOpacity="0.25" />
          <circle cx="8" cy="8" r="5" fill="white" stroke={ISOLATED} strokeWidth="2.2" />
          <circle cx="8" cy="8" r="2" fill={ISOLATED} />
        </>
      )}
      {status === 'cut' && (
        <>
          <line x1="1" y1="8" x2="15" y2="8" stroke={cssColor(IMPACT_COLOR.cut)} strokeWidth="3" strokeLinecap="round" />
          <circle cx="8" cy="8" r="3" fill={cssColor(IMPACT_COLOR.cut)} stroke="white" strokeWidth="1" />
        </>
      )}
      {status === 'at_risk' && (
        <line x1="1" y1="8" x2="15" y2="8" stroke={cssColor(IMPACT_COLOR.atRisk)} strokeWidth="2.2" strokeLinecap="round" />
      )}
      {status === 'ok' && <circle cx="8" cy="8" r="3" fill="rgb(148 163 184)" />}
    </svg>
  )
}
