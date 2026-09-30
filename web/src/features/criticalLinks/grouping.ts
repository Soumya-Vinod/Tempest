import type { CriticalLink, CriticalLinkFacility, Timestep } from '../../types/contracts'
import { linkKey } from './useCriticalLinks'

/**
 * Presentation only (the API's links stay as they are): links that share a road name become one
 * entry; so do unnamed links of the same type with the same block span and the same facilities.
 * Named ferries stay on their own.
 */
export interface LinkEntry {
  key: string
  label: string
  ferry: boolean
  facilities: CriticalLinkFacility[] // union, by deadline then name
  earliest_deadline: Timestep
  segments: LinkSegment[] // the API links, in the API's order
}

export interface LinkSegment {
  key: string
  label: string
  link: CriticalLink
}

export interface LinkGroups {
  roads: LinkEntry[] // named roads grouped by name, and unnamed roads; ranked
  ferries: LinkEntry[] // every ferry link; ranked
}

export const ROADS_SHOWN = 5

/** OSM names holding several values ("A;B") show only the first. */
export function displayName(name: string | null): string | null {
  const first = name?.split(';')[0].trim()
  return first ? first : null
}

function withBlocks(base: string, blocks: string[]): string {
  return blocks.length ? `${base} (${blocks.join(' → ')})` : base
}

function segmentLabel(link: CriticalLink): string {
  const name = displayName(link.name)
  return name ? withBlocks(name, link.blocks) : link.label
}

/**
 * The blocks a stretch runs through, in the direction of travel: each link lists its blocks in
 * that order, so order them by those precedences (first seen breaks ties and cycles).
 */
export function blockOrder(sequences: string[][]): string[] {
  const seen: string[] = []
  const after = new Map<string, Set<string>>()
  const before = new Map<string, number>()
  for (const seq of sequences) {
    for (const b of seq) {
      if (!after.has(b)) {
        seen.push(b)
        after.set(b, new Set())
        before.set(b, 0)
      }
    }
    for (let i = 1; i < seq.length; i++) {
      const [a, b] = [seq[i - 1], seq[i]]
      if (a !== b && !after.get(a)!.has(b)) {
        after.get(a)!.add(b)
        before.set(b, before.get(b)! + 1)
      }
    }
  }
  const out: string[] = []
  const left = new Set(seen)
  while (left.size) {
    const next = seen.find((b) => left.has(b) && before.get(b) === 0) ?? seen.find((b) => left.has(b))!
    left.delete(next)
    out.push(next)
    for (const b of after.get(next)!) before.set(b, before.get(b)! - 1)
  }
  return out
}

function byDeadline(a: CriticalLinkFacility, b: CriticalLinkFacility): number {
  return a.deadline < b.deadline ? -1 : a.deadline > b.deadline ? 1 : a.name.localeCompare(b.name)
}

function entry(key: string, links: CriticalLink[], label: string): LinkEntry {
  const facilities = new Map<string, CriticalLinkFacility>()
  for (const l of links) for (const f of l.facilities) facilities.set(f.infra_id, f)
  const sorted = [...facilities.values()].sort(byDeadline)
  return {
    key,
    label,
    ferry: links[0].link_type === 'ferry',
    facilities: sorted,
    earliest_deadline: sorted[0].deadline,
    segments: links.map((l) => ({ key: `seg:${linkKey(l.way_ids)}`, label: segmentLabel(l), link: l })),
  }
}

/** Most facilities first, then the earliest deadline; on a tie a ferry before a road; then label. */
function rank(a: LinkEntry, b: LinkEntry): number {
  return (
    b.facilities.length - a.facilities.length ||
    (a.earliest_deadline < b.earliest_deadline ? -1 : a.earliest_deadline > b.earliest_deadline ? 1 : 0) ||
    Number(b.ferry) - Number(a.ferry) ||
    a.label.localeCompare(b.label)
  )
}

/** First and last block, or the one block. */
function span(blocks: string[]): string[] {
  return blocks.length > 1 ? [blocks[0], blocks[blocks.length - 1]] : blocks
}

/**
 * Named roads grouped by name (the whole stretch's first → last block); unnamed links grouped by
 * type, block span and facility set; named ferries as they are.
 */
export function groupLinks(links: CriticalLink[]): LinkGroups {
  const named = new Map<string, CriticalLink[]>()
  const unnamed = new Map<string, CriticalLink[]>()
  const entries: LinkEntry[] = []
  for (const l of links) {
    const name = displayName(l.name)
    if (l.link_type === 'road' && name) {
      if (!named.has(name)) named.set(name, [])
      named.get(name)!.push(l)
    } else if (!name) {
      const ids = l.facilities.map((f) => f.infra_id).sort()
      const key = `unnamed:${l.link_type}|${span(l.blocks).join('→')}|${ids.join(',')}`
      if (!unnamed.has(key)) unnamed.set(key, [])
      unnamed.get(key)!.push(l)
    } else {
      entries.push(entry(`link:${linkKey(l.way_ids)}`, [l], segmentLabel(l)))
    }
  }
  for (const [name, group] of named) {
    const order = blockOrder(group.map((l) => l.blocks))
    entries.push(entry(`road:${name}`, group, withBlocks(name, span(order))))
  }
  for (const [key, group] of unnamed) {
    const base = group[0].link_type === 'ferry' ? 'Unnamed ferry route' : 'Unnamed road'
    entries.push(entry(key, group, withBlocks(base, span(group[0].blocks))))
  }
  entries.sort(rank)
  return { roads: entries.filter((e) => !e.ferry), ferries: entries.filter((e) => e.ferry) }
}

/** The links to highlight for an entry or segment key. */
export function linksFor(groups: LinkGroups, key: string | null): CriticalLink[] {
  if (!key) return []
  for (const e of [...groups.roads, ...groups.ferries]) {
    if (e.key === key) return e.segments.map((s) => s.link)
    const seg = e.segments.find((s) => s.key === key)
    if (seg) return [seg.link]
  }
  return []
}

/** The entry an entry or segment key belongs to (for keeping it expanded). */
export function entryOf(groups: LinkGroups, key: string | null): string | null {
  if (!key) return null
  for (const e of [...groups.roads, ...groups.ferries]) {
    if (e.key === key || e.segments.some((s) => s.key === key)) return e.key
  }
  return null
}
