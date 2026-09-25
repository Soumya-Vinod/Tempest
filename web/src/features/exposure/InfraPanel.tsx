import type { Color } from '@deck.gl/core'
import type { ReactNode } from 'react'

import type { InfraFeatureCollection, InfraType } from '../../types/contracts'
import { COLOR, cssColor, INFRA_TYPES, STAND_IN, TYPE_LABEL } from './style'
import type { InfraByType } from './useInfra'

interface Props {
  state: InfraByType
  visible: Record<InfraType, boolean>
  onToggle: (infraType: InfraType) => void
}

const count = (fc: InfraFeatureCollection, key: string, value: unknown) =>
  fc.features.filter((f) => f.properties.attributes[key] === value).length

/** Legend-style breakdown under a row, e.g. hollow vs filled shelters. */
function breakdown(infraType: InfraType, fc: InfraFeatureCollection): ReactNode {
  const n = (v: number) => v.toLocaleString()
  switch (infraType) {
    case 'road': {
      const ferries = count(fc, 'ferry', true)
      const off = count(fc, 'baseline_reachable_from_main', false)
      return `${n(ferries)} ferry routes (blue) · ${n(off)} with no mapped mainland link (grey)`
    }
    case 'hospital': {
      const hospitals = count(fc, 'facility_level', 'hospital')
      const centres = fc.features.length - hospitals
      return `${n(hospitals)} hospitals (large) · ${n(centres)} health centres`
    }
    case 'shelter': {
      const standIns = Object.entries(STAND_IN).map(([kind, s]) => ({
        ...s,
        n: count(fc, 'shelter_kind', kind),
      }))
      const real = fc.features.length - standIns.reduce((sum, s) => sum + s.n, 0)
      return (
        <ul className="space-y-0.5">
          <li className="flex items-center gap-1.5">
            <Dot fill={COLOR.shelter} ring={COLOR.shelter} />
            {n(real)} designated shelters
          </li>
          {standIns.map((s) => (
            <li key={s.label} className="flex items-center gap-1.5">
              <Dot fill={[255, 255, 255]} ring={s.ring} />
              {n(s.n)} {s.plural} (stand-ins)
            </li>
          ))}
        </ul>
      )
    }
    default:
      return null
  }
}

function Dot({ fill, ring }: { fill: Color; ring: Color }) {
  return (
    <span
      className="size-2 shrink-0 rounded-full border-[1.5px]"
      style={{ background: cssColor(fill), borderColor: cssColor(ring) }}
      aria-hidden
    />
  )
}

const SWATCH: Record<InfraType, { color: Color; line: boolean }> = {
  road: { color: COLOR.roadMajor, line: true },
  power_line: { color: COLOR.powerLine, line: true },
  substation: { color: COLOR.substation, line: false },
  hospital: { color: COLOR.hospital, line: false },
  shelter: { color: COLOR.shelter, line: false },
}

function Swatch({ infraType }: { infraType: InfraType }) {
  const { color, line } = SWATCH[infraType]
  return line ? (
    <span className="h-1 w-4 rounded-full" style={{ background: cssColor(color) }} aria-hidden />
  ) : (
    <span
      className="mx-1 size-2.5 rounded-full ring-1 ring-white"
      style={{ background: cssColor(color) }}
      aria-hidden
    />
  )
}

/** "Infrastructure" side-panel section: one toggle and count per type. */
export default function InfraPanel({ state, visible, onToggle }: Props) {
  return (
    <section className="mt-5">
      <h2 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
        Infrastructure
      </h2>
      <ul className="space-y-2">
        {INFRA_TYPES.map((infraType) => {
          const s = state[infraType]
          const detail = s.status === 'ok' ? breakdown(infraType, s.data) : null
          return (
            <li key={infraType}>
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={visible[infraType]}
                  onChange={() => onToggle(infraType)}
                  className="accent-slate-700"
                />
                <Swatch infraType={infraType} />
                <span className="font-medium">{TYPE_LABEL[infraType]}</span>
                <span className="ml-auto text-xs text-slate-500 tabular-nums">
                  {s.status === 'loading' && 'loading…'}
                  {s.status === 'ok' && s.data.features.length.toLocaleString()}
                  {s.status === 'error' && <span className="text-red-600">error</span>}
                </span>
              </label>
              {detail && <div className="mt-0.5 ml-6 text-xs text-slate-500">{detail}</div>}
              {s.status === 'error' && (
                <p className="mt-0.5 ml-6 text-xs text-red-600">{s.message}</p>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
