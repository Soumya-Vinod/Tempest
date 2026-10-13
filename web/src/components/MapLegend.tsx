import { type ReactNode, useState } from 'react'

import { COLOR as INFRA } from '../features/exposure/style'
import { STORM_CSS, SURGE_RAMP_CSS } from '../features/hazard/style'
import type { MapViewMode } from '../features/hazard'
import { StatusSwatch } from '../features/impact'
import { cssColor, HATCH_CSS, RAMP_CSS } from '../features/risk/style'
import { above, CARD_TOP_CLEARANCE, cssLength, useLayout } from '../lib/layout'
import { css, SELECTION, SEVERITY } from '../lib/tokens'
import type { Horizon } from '../types/contracts'

const rgb = (c: readonly number[]) => cssColor([c[0], c[1], c[2], c[3] ?? 255])

/** A 16 px symbol cell. */
function Sym({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 16 16" className="size-4 shrink-0" aria-hidden>
      {children}
    </svg>
  )
}
const Line = ({ color, width = 2, dash }: { color: string; width?: number; dash?: string }) => (
  <Sym>
    <line x1="1" y1="8" x2="15" y2="8" stroke={color} strokeWidth={width} strokeDasharray={dash} strokeLinecap="round" />
  </Sym>
)
const Dot = ({ fill, ring = 'white', r = 4 }: { fill: string; ring?: string; r?: number }) => (
  <Sym>
    <circle cx="8" cy="8" r={r} fill={fill} stroke={ring} strokeWidth="1.5" />
  </Sym>
)

function Row({ symbol, children }: { symbol: ReactNode; children: ReactNode }) {
  return (
    <li className="flex items-center gap-2">
      {symbol}
      <span>{children}</span>
    </li>
  )
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mt-2.5 first:mt-0">
      <p className="mb-1 font-medium text-ink-subtle">{title}</p>
      <ul className="space-y-1">{children}</ul>
    </div>
  )
}

const Ramp = ({ css, from, to }: { css: string; from: string; to: string }) => (
  <li>
    <div className="h-2 w-full rounded-sm" style={{ background: css }} aria-hidden />
    <div className="flex justify-between text-ink-subtle">
      <span>{from}</span>
      <span>{to}</span>
    </div>
  </li>
)

/**
 * What every symbol on the map means, for the current view (Hazard / Risk) and time (Now / Next
 * 24 h). Bottom-left; it folds away while a pathway or block card uses that corner.
 */
/** Which groups the map draws (false: their data failed, nothing of them is on the map). */
export interface LegendDrawn {
  impact: boolean
  risk: boolean
  track: boolean
  surge: boolean
  roads: boolean
  power: boolean
  health: boolean
  shelters: boolean
}

export default function MapLegend({
  view,
  horizon,
  cardOpen,
  drawn,
  payouts,
  atRisk = false,
}: {
  view: MapViewMode
  horizon: Horizon
  cardOpen: boolean
  drawn: LegendDrawn
  /** The payout outline is drawn (Finance tab open). */
  payouts: boolean
  /** At-risk roads and lines are on (Layers); at-risk facilities show in the Risk view too. */
  atRisk?: boolean
}) {
  // Folded on short screens, where it would cover much of the map: at first, and again whenever
  // a resize crosses into them (unfolded when it crosses out). The user's toggle holds otherwise.
  const layout = useLayout()
  const { aboveTimeline, legendFolded, gap, phone } = layout
  const bottom = above(layout, aboveTimeline)
  const [fold, setFold] = useState({ folded: legendFolded, open: !legendFolded })
  if (fold.folded !== legendFolded) setFold({ folded: legendFolded, open: !legendFolded })
  const { open } = fold
  const setOpen = (toggle: (open: boolean) => boolean) => setFold((f) => ({ ...f, open: toggle(f.open) }))
  const expanded = open && !cardOpen
  const missing = [
    !drawn.impact && 'impact',
    !drawn.track && 'storm track',
    view === 'hazard' && !drawn.surge && 'storm surge',
    view === 'risk' && !drawn.risk && 'risk by block',
    !drawn.roads && 'roads',
    !drawn.power && 'power lines',
    !drawn.health && 'health facilities',
    !drawn.shelters && 'shelters',
  ].filter((x): x is string => !!x)
  return (
    <section
      aria-label="Map legend"
      className={`absolute z-10 w-52 overflow-y-auto rounded-panel border border-line bg-white/95 text-[11px] text-ink-muted shadow-sm ${
        phone ? 'sheet-rides sheet-hides' : ''
      }`}
      style={{
        left: gap,
        bottom,
        maxHeight: `calc(100% - ${cssLength(bottom)} - ${CARD_TOP_CLEARANCE}px)`,
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={expanded}
        disabled={cardOpen}
        className="flex w-full items-center justify-between px-3 py-1.5 text-xs font-medium text-ink disabled:text-ink-subtle"
      >
        Legend · {view === 'hazard' ? 'Hazard' : 'Risk'}, {horizon === 24 ? 'next 24 h' : 'now'}
        <span aria-hidden>{expanded ? '▾' : '▸'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-2">
          {drawn.impact && (
            <Group title="Facilities">
              <Row symbol={<StatusSwatch status="isolated" />}>Cut off</Row>
              {horizon === 24 && (
                <Row symbol={<StatusSwatch status="isolated" expected />}>Expected to be cut off (24 h)</Row>
              )}
              {(view === 'risk' || atRisk) && (
                <Row symbol={<Dot fill={css(SEVERITY.watch)} r={3} />}>At risk</Row>
              )}
            </Group>
          )}
          {drawn.impact && (
            <Group title="Roads and lines">
              <Row symbol={<StatusSwatch status="cut" />}>Cut</Row>
              {atRisk && <Row symbol={<StatusSwatch status="at_risk" />}>At risk</Row>}
              <Row symbol={<Line color={css(SELECTION)} width={3} />}>Selected</Row>
            </Group>
          )}
          {drawn.track && (
            <Group title="Storm">
              <Row symbol={<Line color={STORM_CSS.track} width={2} />}>Track so far</Row>
              <Row symbol={<Line color={STORM_CSS.next} width={2.75} />}>Next 24 h</Row>
              <Row symbol={<Line color={STORM_CSS.later} width={1.5} dash="3 2.5" />}>Later</Row>
              <Row symbol={<Dot fill={STORM_CSS.storm} r={4} />}>Storm now</Row>
            </Group>
          )}
          {view === 'hazard' && drawn.surge && (
            <Group title={horizon === 24 ? 'Storm surge, max next 24 h' : 'Storm surge depth'}>
              <Ramp css={SURGE_RAMP_CSS} from="0 m" to="6 m" />
            </Group>
          )}
          {view === 'risk' && drawn.risk && (
            <Group title="Risk by block">
              <Ramp css={RAMP_CSS} from="0 low" to="1 high" />
              <Row
                symbol={
                  <span className="block size-4 shrink-0 rounded-sm border border-slate-300" style={{ background: HATCH_CSS }} />
                }
              >
                Municipal area, not scored
              </Row>
            </Group>
          )}
          {payouts && (
            <Group title="Finance">
              <Row symbol={<Line color="rgb(202 138 4)" width={2} />}>Insurance payout released</Row>
            </Group>
          )}
          {(drawn.roads || drawn.power || drawn.health || drawn.shelters) && (
            <Group title="Network">
              {drawn.roads && <Row symbol={<Line color={rgb(INFRA.roadMajor)} width={3.5} />}>Major roads</Row>}
              {drawn.roads && <Row symbol={<Line color={rgb(INFRA.roadMinor)} />}>Other roads</Row>}
              {drawn.roads && <Row symbol={<Line color={rgb(INFRA.ferry)} dash="4 2.5" />}>Ferry routes (dashed)</Row>}
              {drawn.power && (
                <Row symbol={<Line color={rgb(INFRA.powerLine)} dash="0.5 2.5" />}>Power lines (dotted)</Row>
              )}
              {drawn.health && <Row symbol={<Dot fill={rgb(INFRA.hospital)} />}>Hospital / health centre</Row>}
              {drawn.shelters && <Row symbol={<Dot fill={rgb(INFRA.shelter)} />}>Shelter (hollow: stand-in)</Row>}
            </Group>
          )}
          {missing.length > 0 && (
            <p className="mt-2 text-ink-subtle">
              Not on the map (data unavailable): {missing.join(', ')}.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
