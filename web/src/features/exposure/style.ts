// Colours, sizes and plain-word labels for the infrastructure layers and panel.
import type { Color } from '@deck.gl/core'

import type { InfraType } from '../../types/contracts'

/** Panel order, top to bottom. */
export const INFRA_TYPES: readonly InfraType[] = [
  'road',
  'power_line',
  'substation',
  'hospital',
  'shelter',
]

export const TYPE_LABEL: Record<InfraType, string> = {
  road: 'Roads & ferries',
  power_line: 'Power lines',
  substation: 'Substations',
  hospital: 'Health facilities',
  shelter: 'Shelters',
}

/**
 * The network is slate, told apart by shape (major roads thicker, ferries dashed, power lines
 * dotted), so no hue is shared with a symbol that means something else: red / amber are impact,
 * gold the payout, blue surge, violet risk, pink the storm.
 */
export const COLOR = {
  roadMajor: [30, 41, 59], // slate-800, thicker: motorway, trunk, primary
  roadMinor: [100, 116, 139], // slate-500
  ferry: [71, 85, 105], // slate-600, dashed
  noMainland: [148, 163, 184, 120], // slate-400, translucent: muted
  powerLine: [100, 116, 139], // slate-500, dotted
  substation: [51, 65, 85], // slate-700
  hospital: [13, 148, 136], // teal-600 (red and orange are reserved for impact)
  healthCentre: [45, 212, 191], // teal-400
  shelter: [22, 163, 74], // green-600
  outline: [255, 255, 255],
  standInFill: [255, 255, 255], // opaque white inside a ring: reads hollow, stays pickable
} satisfies Record<string, Color>

/**
 * While impact results are showing, exposure steps back so red and orange read as impact only:
 * greys by road class, pale tints for ferries and power lines, neutral points. Shelters keep
 * filled (designated) vs hollow (stand-in).
 */
export const MUTED = {
  roadMajor: [100, 116, 139], // slate-500: motorway, trunk, primary
  roadMid: [148, 163, 184], // slate-400: secondary, tertiary
  roadMinor: [203, 213, 225], // slate-300: unclassified, links
  ferry: [148, 163, 184], // slate-400, dashed
  noMainland: [226, 232, 240, 140], // slate-200, translucent
  powerLine: [203, 213, 225], // slate-300, dotted
  substation: [168, 162, 158], // stone-400
  hospital: [120, 113, 108], // stone-500
  healthCentre: [168, 162, 158], // stone-400
  shelter: [161, 161, 170], // zinc-400 (filled)
  standInRing: [161, 161, 170], // zinc-400 (hollow)
} satisfies Record<string, Color>

/** Road line width (px) by OSM highway class; `_link` roads use LINK_WIDTH. */
/** Layer opacity of the baseline network: context, not the story. */
export const ROAD_OPACITY = 0.5
export const POWER_LINE_OPACITY = 0.6

export const ROAD_WIDTH: Record<string, number> = {
  motorway: 4.5,
  trunk: 4.5,
  primary: 4,
  secondary: 2.5,
  tertiary: 2,
  unclassified: 1.2,
}
export const LINK_WIDTH = 1.5
export const FERRY_WIDTH = 2
export const MAJOR_ROADS = new Set(['motorway', 'trunk', 'primary'])

/** Plain words for OSM highway classes. */
export const HIGHWAY_LABEL: Record<string, string> = {
  motorway: 'Motorway',
  trunk: 'Trunk road',
  primary: 'Primary road',
  secondary: 'Secondary road',
  tertiary: 'Tertiary road',
  unclassified: 'Minor road',
}

/**
 * Point radii in px as [at AOI zoom, full size]. Radii are set in metres (full size x
 * FULL_SIZE_M_PER_PX) and clamped to this range, so points grow from ~2-3 px at the AOI view to
 * full size around zoom 13 (~25 m/px at 22° N). Hospitals stay larger than health centres.
 */
export const POINT_PX = {
  substation: [2, 4.5],
  hospital: [3, 6],
  healthCentre: [2, 4],
  shelter: [2.5, 5],
} as const satisfies Record<string, readonly [number, number]>
export const FULL_SIZE_M_PER_PX = 25
export const OUTLINE_PX = 0.75 // white edge on filled points
export const STAND_IN_RING_PX = 1.5 // coloured ring on hollow stand-in markers

/**
 * Shelter stand-ins (shelter_kind *_proxy): buildings that could shelter people but are not
 * designated shelters. Each is a hollow marker with its own ring colour; real shelters are filled.
 */
export const STAND_IN: Record<string, { ring: Color; label: string; plural: string }> = {
  school_proxy: { ring: [22, 163, 74], label: 'school or college', plural: 'schools & colleges' },
  community_proxy: {
    ring: [14, 116, 144], // cyan-700
    label: 'community centre',
    plural: 'community centres',
  },
  public_building_proxy: {
    ring: [79, 70, 229], // indigo-600
    label: 'public building',
    plural: 'public buildings',
  },
}

export const cssColor = ([r, g, b, a = 255]: Color) => `rgb(${r} ${g} ${b} / ${a / 255})`
