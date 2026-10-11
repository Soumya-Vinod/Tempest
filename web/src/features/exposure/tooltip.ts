// Hover tooltip for infrastructure features: name, type and key attributes in plain words.
import type { DeckProps, PickingInfo } from '@deck.gl/core'

import type { InfraFeature } from '../../types/contracts'
import type { BlockOf } from './blocks'
import { HIGHWAY_LABEL, STAND_IN } from './style'

type Attrs = Record<string, unknown>
/** deck.gl's tooltip return type (not exported from the package root). */
type TooltipContent = ReturnType<NonNullable<DeckProps['getTooltip']>>

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** What the feature is, in plain words (also used for "Unnamed …"). */
export function kindLabel(infraType: InfraFeature['properties']['infra_type'], a: Attrs): string {
  switch (infraType) {
    case 'road': {
      if (a.ferry === true) return 'Ferry route'
      const hw = String(a.highway ?? '')
      if (hw.endsWith('_link')) return 'Slip road'
      return HIGHWAY_LABEL[hw] ?? 'Road'
    }
    case 'power_line':
      return 'Power line'
    case 'substation':
      return 'Substation'
    case 'hospital':
      return a.facility_level === 'hospital' ? 'Hospital' : 'Health centre'
    case 'shelter':
      if (a.shelter_kind === 'cyclone_shelter') return 'Cyclone shelter'
      if (a.shelter_kind === 'assembly_point') return 'Assembly point'
      return capitalise(STAND_IN[String(a.shelter_kind)]?.label ?? 'shelter')
  }
}

/** "132000;33000" -> "132 kV / 33 kV"; non-numeric parts are shown as-is. */
export function formatVoltage(v: unknown): string {
  return String(v)
    .split(';')
    .map((part) => {
      const volts = Number(part.trim())
      return Number.isFinite(volts) && volts > 0 ? `${volts / 1000} kV` : part.trim()
    })
    .join(' / ')
}

function details(infraType: InfraFeature['properties']['infra_type'], a: Attrs): string[] {
  const lines: string[] = []
  if (a.voltage) lines.push(`Voltage: ${formatVoltage(a.voltage)}`)
  if (a.operator) lines.push(`Operator: ${String(a.operator)}`)
  if (a.ref) lines.push(`Route number: ${String(a.ref)}`)
  if (a.bridge && a.bridge !== 'no') lines.push('Bridge')
  const standIn = infraType === 'shelter' ? STAND_IN[String(a.shelter_kind)] : undefined
  if (standIn) lines.push(`Stand-in: ${standIn.label}, not a designated shelter`)
  if (infraType === 'road' && a.baseline_reachable_from_main === false) {
    lines.push('No mapped connection to mainland')
  }
  return lines
}

/**
 * A name for a feature OSM leaves unnamed, with its CD block when known: "Road segment ·
 * Kultali", "Ferry route segment", "Unnamed health centre · Gosaba".
 */
export function unnamedLabel(f: InfraFeature, block: string | null): string {
  const { infra_type, attributes } = f.properties
  let base: string
  if (infra_type === 'power_line') base = 'Power line segment'
  else if (infra_type === 'road')
    base = attributes.ferry === true ? 'Ferry route segment' : 'Road segment'
  else base = `Unnamed ${kindLabel(infra_type, attributes).toLowerCase()}`
  return block ? `${base} · ${block}` : base
}

/** The feature's name, or unnamedLabel (its block looked up lazily, for this feature only). */
export function displayName(f: InfraFeature, blockOf: BlockOf | null): string {
  return f.properties.name ?? unnamedLabel(f, blockOf?.(f.id, f.geometry) ?? null)
}

export function tooltipLines(f: InfraFeature, blockOf: BlockOf | null = null): string[] {
  const { infra_type, attributes } = f.properties
  const kind = kindLabel(infra_type, attributes)
  return [displayName(f, blockOf), kind, ...details(infra_type, attributes)]
}

const STYLE: Partial<CSSStyleDeclaration> = {
  backgroundColor: 'white',
  color: '#1e293b',
  fontSize: '12px',
  lineHeight: '1.4',
  padding: '6px 8px',
  borderRadius: '6px',
  boxShadow: '0 2px 8px rgb(0 0 0 / 0.2)',
  maxWidth: '260px',
}

/** deck.gl getTooltip for the infra-* layers; plain text, so OSM names can't inject HTML. */
export function makeInfraTooltip(blockOf: BlockOf | null) {
  return (info: PickingInfo): TooltipContent => {
    if (!info.object || !info.layer?.id.startsWith('infra-')) return null
    return { text: tooltipLines(info.object as InfraFeature, blockOf).join('\n'), style: STYLE }
  }
}
