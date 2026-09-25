// Hover tooltip for infrastructure features: name, type and key attributes in plain words.
import type { DeckProps, PickingInfo } from '@deck.gl/core'

import type { InfraFeature } from '../../types/contracts'
import { HIGHWAY_LABEL } from './style'

type Attrs = Record<string, unknown>
/** deck.gl's tooltip return type (not exported from the package root). */
type TooltipContent = ReturnType<NonNullable<DeckProps['getTooltip']>>

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
      return 'School'
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
  if (infraType === 'shelter' && a.shelter_kind === 'school_proxy') {
    lines.push('Stand-in: not a designated cyclone shelter')
  }
  if (infraType === 'road' && a.baseline_reachable_from_main === false) {
    lines.push('No mapped connection to mainland')
  }
  return lines
}

export function tooltipLines(f: InfraFeature): string[] {
  const { infra_type, name, attributes } = f.properties
  const kind = kindLabel(infra_type, attributes)
  return [name ?? `Unnamed ${kind.toLowerCase()}`, kind, ...details(infra_type, attributes)]
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
export function infraTooltip(info: PickingInfo): TooltipContent {
  if (!info.object || !info.layer?.id.startsWith('infra-')) return null
  return { text: tooltipLines(info.object as InfraFeature).join('\n'), style: STYLE }
}
