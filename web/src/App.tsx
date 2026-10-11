import type { PickingInfo } from '@deck.gl/core'
import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useMemo, useState } from 'react'

import HealthPanel from './components/HealthPanel'
import MapErrorBoundary from './components/MapErrorBoundary'
import MapLegend from './components/MapLegend'
import MapView from './components/MapView'
import PanelTabs from './components/PanelTabs'
import TimelineScrubber from './components/TimelineScrubber'
import WakingNotice from './components/WakingNotice'
import { AboutPanel } from './features/about'
import { AdvisoryDrawer, AdvisoryPanel, useAdvisories } from './features/advisory'
import { CountdownPanel, useCountdown } from './features/countdown'
import {
  buildLinkLayers,
  groupLinks,
  KeepOpenPanel,
  linksFor,
  useCriticalLinks,
} from './features/criticalLinks'
import { buildRouteLayers, useDepartures } from './features/departures'
import {
  type FacilityFilter,
  InfraPanel,
  makeInfraTooltip,
  useBlockOf,
  useInfraLayers,
  useInfraMap,
} from './features/exposure'
import { HazardPanel, type MapViewMode, StormEdge, useHazardMap } from './features/hazard'
import { ImpactPanel, PathwayCard, useImpactMap } from './features/impact'
import { InsurancePanel, useInsuranceMap } from './features/insurance'
import { KpiStrip, useKpis } from './features/kpi'
import { RiskCard, RiskPanel, useRiskMap } from './features/risk'
import { useTimeline } from './lib/timeline'
import type { Horizon } from './types/contracts'

export default function App() {
  const timeline = useTimeline()
  // Replay index into the timeline's timesteps; features read the timestep from here.
  const [chosenIndex, setTimestepIndex] = useState(0)
  // Clamped: the API's timeline replaces the fallback and could be shorter.
  const timestepIndex = Math.min(chosenIndex, timeline.timesteps.length - 1)
  // The user's Hazard / Risk choice; null until they pick one (then the view is automatic:
  // Hazard until a block reaches the advisory threshold at this timestep, Risk after).
  const [chosenView, setChosenView] = useState<MapViewMode | null>(null)
  const [map, setMap] = useState<MapLibreMap | null>(null)
  // Now / Next 24 h (v1.3): the user's choice, or null = Next 24 h before landfall (there is
  // nothing ahead to forecast at landfall itself).
  const [chosenHorizon, setChosenHorizon] = useState<Horizon | null>(null)
  const horizon: Horizon = chosenHorizon ?? (timestepIndex < timeline.landfallIndex ? 24 : 0)

  const infra = useInfraMap()
  const risk = useRiskMap(timestepIndex, chosenView, horizon)
  // Unnamed features are labelled by block ("Road segment · Kultali"), looked up on hover.
  const blockOf = useBlockOf(risk.areas)
  const infraTooltip = useMemo(() => makeInfraTooltip(blockOf), [blockOf])
  const impact = useImpactMap(timestepIndex, infra.state, horizon, blockOf, map)
  const hazard = useHazardMap(timestepIndex, risk.view, setChosenView, map, horizon, setChosenHorizon)
  const insurance = useInsuranceMap(timestepIndex, risk.view === 'risk')
  const countdown = useCountdown(timeline.timesteps[timestepIndex])
  const departures = useDepartures()
  const departure = impact.card.selectedId
    ? (departures.get(impact.card.selectedId) ?? null)
    : null
  const routeLayers = useMemo(() => buildRouteLayers(departure), [departure])
  // Keep these open (v1.4): links grouped for the panel (roads by name); the hovered entry or
  // segment, else the clicked one, on the map.
  const criticalLinks = useCriticalLinks(timeline.timesteps[timestepIndex], horizon)
  const [hoveredLink, setHoveredLink] = useState<string | null>(null)
  const [pinnedLink, setPinnedLink] = useState<string | null>(null)
  const linkGroups = useMemo(
    () => (criticalLinks.status === 'ok' ? groupLinks(criticalLinks.data.links) : null),
    [criticalLinks],
  )
  const linkLayers = useMemo(
    () => buildLinkLayers(linkGroups ? linksFor(linkGroups, hoveredLink ?? pinnedLink) : []),
    [linkGroups, hoveredLink, pinnedLink],
  )
  // Shelter stand-ins have no departure: the card only says since when they are cut off.
  const shelterCutOff =
    countdown.state.status === 'ok'
      ? countdown.state.data.cut_off.find(
          (f) => f.infra_id === impact.card.selectedId && f.infra_type === 'shelter',
        )
      : undefined
  const shelterSince = timeline.indexOf(shelterCutOff?.since)
  // Less noise: health facilities and shelters only where something is happening (affected, or
  // in a block at risk), unless the user shows them all. The block test is lazy and memoized.
  const { affectedIds } = impact
  const { atRiskBlocks } = risk
  const facilityFilter = useMemo<FacilityFilter>(
    () => (f) =>
      affectedIds.has(f.id) || (blockOf !== null && atRiskBlocks.has(blockOf(f.id, f.geometry) ?? '')),
    [affectedIds, atRiskBlocks, blockOf],
  )
  // Red and orange mean impact only: exposure mutes its colours while impact results show.
  const infraLayers = useInfraLayers(infra, impact.active, facilityFilter)

  // Bottom to top: hazard fills or the risk choropleth (one view at a time: both are area
  // fills; in Risk view, gold outlines on blocks with an insurance payout released), muted
  // exposure, impact, the storm track, the selected facility's departure route (v1.3), the
  // highlighted critical link (v1.4), then the selection highlights.
  const layers = useMemo(
    () => [
      ...hazard.fillLayers,
      ...risk.layers,
      ...insurance.layers,
      ...infraLayers,
      ...impact.layers,
      ...hazard.trackLayers,
      ...routeLayers,
      ...linkLayers,
      ...risk.highlightLayers,
      ...impact.highlightLayers,
    ],
    [
      hazard.fillLayers,
      risk.layers,
      insurance.layers,
      infraLayers,
      impact.layers,
      hazard.trackLayers,
      routeLayers,
      linkLayers,
      risk.highlightLayers,
      impact.highlightLayers,
    ],
  )
  const { tooltip: impactTooltip, onClick: impactClick, clear: impactClear } = impact
  const { tooltip: riskTooltip, onClick: riskClick, clear: riskClear, select: riskSelect } = risk
  const { tooltip: hazardTooltip } = hazard
  // Opening an advisory selects its block on the map (one card at a time, as a click does) and
  // switches to the Risk view, which counts as the user's choice.
  const selectBlock = useCallback(
    (blockId: string) => {
      impactClear()
      setChosenView('risk')
      riskSelect(blockId)
    },
    [impactClear, riskSelect],
  )
  // Facilities already cut off now, so suggestions don't call them "expected to be cut off".
  const cutOff = useMemo(
    () =>
      new Map(
        countdown.state.status === 'ok'
          ? countdown.state.data.cut_off.map((f) => {
              const since = timeline.indexOf(f.since)
              const when = since >= 0 && since < timestepIndex ? `since ${timeline.label(since)}` : 'now'
              return [f.infra_id, { name: f.name, when }]
            })
          : [],
      ),
    [countdown.state, timeline, timestepIndex],
  )
  const advisory = useAdvisories(timestepIndex, risk.blocks, selectBlock, cutOff)
  // Facilities to act on now: expected to be cut off, or already cut off. Any: the Act tab opens
  // by default (until the user picks a tab) and shows the count.
  const toAct =
    countdown.state.status === 'ok'
      ? countdown.state.data.expected.length + countdown.state.data.cut_off.length
      : 0
  const kpis = useKpis({
    timestepIndex,
    horizon,
    countdown: countdown.state,
    insurance: insurance.panel.summary,
    advisories: { drafts: advisory.panel.drafts, approved: advisory.panel.approved },
  })
  const getTooltip = useCallback(
    (info: PickingInfo) =>
      impactTooltip(info) ?? riskTooltip(info) ?? hazardTooltip(info) ?? infraTooltip(info),
    [impactTooltip, riskTooltip, hazardTooltip, infraTooltip],
  )
  // One card at a time in the bottom-left slot: an impact feature wins (it's drawn on top),
  // otherwise a block; an empty click closes both.
  const onClick = useCallback(
    (info: PickingInfo) => {
      if (impactClick(info)) riskClear()
      else riskClick(info)
    },
    [impactClick, riskClick, riskClear],
  )
  const onMapLoad = useCallback(
    (m: MapLibreMap) => {
      risk.onMapLoad(m)
      setMap(m)
    },
    [risk],
  )
  // The map was removed (e.g. remounted after a map error): forget it until the new one loads.
  const onMapRemove = useCallback(() => {
    risk.onMapLoad(null)
    setMap(null)
  }, [risk])

  return (
    <main className="relative h-full w-full overflow-hidden">
      {/* Only the map is behind the boundary: if it fails, the panels and timeline stay up. */}
      <MapErrorBoundary>
        <MapView
          layers={layers}
          getTooltip={getTooltip}
          onClick={onClick}
          onMapLoad={onMapLoad}
          onMapRemove={onMapRemove}
        />
      </MapErrorBoundary>
      <StormEdge {...hazard.edge} />
      <KpiStrip {...kpis} />
      <MapLegend
        view={risk.view}
        horizon={horizon}
        cardOpen={impact.card.selectedId !== null || risk.card.selected !== null}
      />
      <HealthPanel>
        <PanelTabs
          automatic={toAct > 0 ? 'act' : 'situation'}
          tabs={[
            {
              id: 'act',
              label: 'Act',
              badge: toAct,
              content: (
                <>
                  <CountdownPanel
                    state={countdown.state}
                    departures={departures}
                    timestepIndex={timestepIndex}
                  />
                  <KeepOpenPanel
                    state={criticalLinks}
                    groups={linkGroups}
                    horizon={horizon}
                    pinned={pinnedLink}
                    onHover={setHoveredLink}
                    onPin={setPinnedLink}
                  />
                  <AdvisoryPanel {...advisory.panel} />
                </>
              ),
            },
            {
              id: 'situation',
              label: 'Situation',
              content: (
                <>
                  <HazardPanel {...hazard.panel} />
                  <RiskPanel {...risk.panel} />
                  <ImpactPanel {...impact.panel} />
                </>
              ),
            },
            { id: 'finance', label: 'Finance', content: <InsurancePanel {...insurance.panel} /> },
            {
              id: 'layers',
              label: 'Layers',
              content: (
                <>
                  <InfraPanel
                    state={infra.state}
                    visible={infra.visible}
                    onToggle={infra.toggle}
                    muted={impact.active}
                    showAllFacilities={infra.showAllFacilities}
                    onToggleShowAll={infra.toggleShowAllFacilities}
                  />
                  <AboutPanel />
                </>
              ),
            },
          ]}
        />
      </HealthPanel>
      <PathwayCard
        {...impact.card}
        departure={departure}
        timestepIndex={timestepIndex}
        shelterCutOffFrom={shelterSince >= 0 ? timeline.label(shelterSince) : null}
      />
      <RiskCard {...risk.card} />
      <AdvisoryDrawer {...advisory.drawer} />
      <WakingNotice />
      <TimelineScrubber
        index={timestepIndex}
        onChange={setTimestepIndex}
        moments={countdown.moments}
      />
    </main>
  )
}
