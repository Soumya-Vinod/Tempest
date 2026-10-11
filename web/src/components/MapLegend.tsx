import { type ReactNode, useState } from 'react'

import { COLOR as INFRA } from '../features/exposure/style'
import { SURGE_RAMP_CSS } from '../features/hazard/style'
import type { MapViewMode } from '../features/hazard'
import { StatusSwatch } from '../features/impact'
import { cssColor, HATCH_CSS, RAMP_CSS } from '../features/risk/style'
import { ABOVE_TIMELINE, CARD_TOP_CLEARANCE, UI_GAP } from '../lib/layout'
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
    <div>
      <p className="mt-2 mb-0.5 text-[10px] font-semibold tracking-wide text-slate-500 uppercase first:mt-0">
        {title}
      </p>
      <ul className="space-y-0.5">{children}</ul>
    </div>
  )
}

const Ramp = ({ css, from, to }: { css: string; from: string; to: string }) => (
  <li>
    <div className="h-2 w-full rounded" style={{ background: css }} aria-hidden />
    <div className="flex justify-between text-[10px] text-slate-500">
      <span>{from}</span>
      <span>{to}</span>
    </div>
  </li>
)

/**
 * What every symbol on the map means, for the current view (Hazard / Risk) and time (Now / Next
 * 24 h). Bottom-left; it folds away while a pathway or block card uses that corner.
 */
export default function MapLegend({
  view,
  horizon,
  cardOpen,
}: {
  view: MapViewMode
  horizon: Horizon
  cardOpen: boolean
}) {
  const [open, setOpen] = useState(true)
  const expanded = open && !cardOpen
  return (
    <section
      aria-label="Map legend"
      className="absolute z-10 w-56 overflow-y-auto rounded-lg bg-white/95 text-[11px] text-slate-700 shadow-lg"
      style={{
        left: UI_GAP,
        bottom: ABOVE_TIMELINE,
        maxHeight: `calc(100% - ${ABOVE_TIMELINE + CARD_TOP_CLEARANCE}px)`,
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={expanded}
        disabled={cardOpen}
        className="flex w-full items-center justify-between px-3 py-1.5 text-xs font-semibold text-slate-700 disabled:text-slate-400"
      >
        Legend · {view === 'hazard' ? 'Hazard' : 'Risk'}, {horizon === 24 ? 'next 24 h' : 'now'}
        <span aria-hidden>{expanded ? '▾' : '▸'}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-2">
          <Group title="Impact">
            <Row symbol={<StatusSwatch status="isolated" />}>Cut off now (isolated facility)</Row>
            {horizon === 24 && (
              <Row symbol={<StatusSwatch status="isolated" expected />}>
                Expected to be cut off within 24 h
              </Row>
            )}
            <Row symbol={<StatusSwatch status="cut" />}>Road, line or substation cut</Row>
            <Row symbol={<StatusSwatch status="at_risk" />}>At risk</Row>
            <Row symbol={<Line color="rgb(6 182 212)" width={4} />}>Selected (cyan outline)</Row>
          </Group>
          <Group title="Storm">
            <Row symbol={<Line color="rgb(30 41 59)" width={3} />}>Track so far</Row>
            <Row symbol={<Line color="rgb(30 41 59 / 0.6)" dash="3 2.5" />}>Track ahead</Row>
            <Row symbol={<Dot fill="rgb(220 38 38)" r={5} />}>Storm now</Row>
          </Group>
          {view === 'hazard' ? (
            <Group title={horizon === 24 ? 'Storm surge (max, next 24 h)' : 'Storm surge depth'}>
              <Ramp css={SURGE_RAMP_CSS} from="0 m" to="6 m" />
            </Group>
          ) : (
            <Group title="Risk by block">
              <Ramp css={RAMP_CSS} from="0 low" to="1 high" />
              <Row
                symbol={
                  <span className="block size-4 shrink-0 rounded-sm border border-slate-300" style={{ background: HATCH_CSS }} />
                }
              >
                Municipal area, not scored
              </Row>
              <Row symbol={<Line color="rgb(202 138 4)" width={3} />}>Insurance payout released</Row>
            </Group>
          )}
          <Group title="Network">
            <Row symbol={<Line color={rgb(INFRA.roadMinor)} />}>Roads (orange: major)</Row>
            <Row symbol={<Line color={rgb(INFRA.ferry)} />}>Ferry routes</Row>
            <Row symbol={<Dot fill={rgb(INFRA.hospital)} />}>Hospital / health centre</Row>
            <Row symbol={<Dot fill={rgb(INFRA.shelter)} />}>Shelter (hollow: stand-in)</Row>
          </Group>
        </div>
      )}
    </section>
  )
}
