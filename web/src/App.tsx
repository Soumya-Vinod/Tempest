import type { PickingInfo } from '@deck.gl/core'
import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useMemo, useState } from 'react'

import Deferred from './components/Deferred'
import HealthPanel from './components/HealthPanel'
import MapErrorBoundary from './components/MapErrorBoundary'
import MapLegend from './components/MapLegend'
import LazyMapView from './components/LazyMapView'
import PanelTabs, { type TabId } from './components/PanelTabs'
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
import { AtRiskToggle, ImpactPanel, PathwayCard, useImpactMap } from './features/impact'
import { InsurancePanel, useInsuranceMap } from './features/insurance'
import { KpiStrip, useKpis } from './features/kpi'
import { RiskCard, RiskPanel, useRiskMap } from './features/risk'
import { useDeck } from './lib/deck'
import { failed } from './lib/loadState'
import { usePrefetchAround } from './lib/prefetch'
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
  const impact = useImpactMap(timestepIndex, infra.state, horizon, blockOf, risk.view)
  const hazard = useHazardMap(timestepIndex, risk.view, setChosenView, map, horizon, setChosenHorizon)
  // The payout outline is a Finance detail: drawn only while that tab is open.
  const [panelTab, setPanelTab] = useState<TabId | null>(null)
  const financeOpen = panelTab === 'finance'
  const insurance = useInsuranceMap(timestepIndex, financeOpen)
  // Warm the steps around this one (low priority: never delays the current step or Play).
  usePrefetchAround(timestepIndex, timeline.timesteps, horizon, risk.view === 'hazard')
  const countdown = useCountdown(timeline.timesteps[timestepIndex])
  const departures = useDepartures()
  const departure = impact.card.selectedId
    ? (departures.get(impact.card.selectedId) ?? null)
    : null
  const deck = useDeck()
  const routeLayers = useMemo(
    () => (deck ? buildRouteLayers(deck, departure) : []),
    [deck, departure],
  )
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
    () =>
      deck ? buildLinkLayers(deck, linkGroups ? linksFor(linkGroups, hoveredLink ?? pinnedLink) : []) : [],
    [deck, linkGroups, hoveredLink, pinnedLink],
  )
  // Shelter stand-ins have no departure: the card only says since when they are cut off.
  const shelterCutOff =
    countdown.state.status === 'ok'
      ? countdown.state.data.cut_off.find(
          (f) => f.infra_id === impact.card.selectedId && f.infra_type === 'shelter',
        )
      : undefined
  const shelterSince = timeline.indexOf(shelterCutOff?.since)
  // Less noise: health facilities and shelters in full only where something is happening
  // (affected, or in a block at risk), the rest faint, unless the user highlights all. The block
  // test is lazy and memoized.
  const { affectedIds } = impact
  const { atRiskBlocks } = risk
  const facilityFilter = useMemo<FacilityFilter>(
    () => (f) =>
      affectedIds.has(f.id) || (blockOf !== null && atRiskBlocks.has(blockOf(f.id, f.geometry) ?? '')),
    [affectedIds, atRiskBlocks, blockOf],
  )
  // Red and orange mean impact only: exposure mutes its colours while impact results show.
  const infraLayers = useInfraLayers(infra, impact.active, facilityFilter, map)

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
  })
  // What the map actually draws: a group whose data failed (with nothing from an earlier step
  // still shown) leaves the legend, which says so instead of describing layers that aren't there.
  const drawn = {
    impact: !failed(impact.panel.state) || impact.active,
    risk: !failed(risk.panel.state) || risk.areas !== null,
    track: !failed(hazard.panel.storm.state),
    surge: !failed(hazard.panel.surge),
    roads: !failed(infra.state.road),
    power: !failed(infra.state.power_line),
    health: !failed(infra.state.hospital),
    shelters: !failed(infra.state.shelter),
  }
  // The timeline's key moments come with the countdown; without them only Landfall is marked.
  const markersFailed = failed(countdown.state) && countdown.moments.length === 0
  // A pathway or block card is open in the bottom-left slot.
  const cardOpen = impact.card.selectedId !== null || risk.card.selected !== null
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
        <LazyMapView
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
        cardOpen={cardOpen}
        drawn={drawn}
        payouts={financeOpen}
      />
      {/* On phones a bottom sheet, which drops back to peek when a card opens on the map. */}
      <HealthPanel collapse={cardOpen}>
        <PanelTabs
          automatic={toAct > 0 ? 'act' : 'situation'}
          onActive={setPanelTab}
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
                    onHighlight={impact.highlight}
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
                  <AtRiskToggle {...impact.atRisk} />
                  <InfraPanel
                    state={infra.state}
                    visible={infra.visible}
                    onToggle={infra.toggle}
                    muted={impact.active}
                    highlightAllFacilities={infra.highlightAllFacilities}
                    onToggleHighlightAll={infra.toggleHighlightAllFacilities}
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
      <Deferred when={advisory.drawer.open}>
        <AdvisoryDrawer {...advisory.drawer} />
      </Deferred>
      <WakingNotice />
      <TimelineScrubber
        index={timestepIndex}
        onChange={setTimestepIndex}
        moments={countdown.moments}
        markersFailed={markersFailed}
      />
    </main>
  )
}
