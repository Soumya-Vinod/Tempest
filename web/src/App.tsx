import type { PickingInfo } from '@deck.gl/core'
import type { Map as MapLibreMap } from 'maplibre-gl'
import { useCallback, useMemo, useState } from 'react'

import HealthPanel from './components/HealthPanel'
import MapView from './components/MapView'
import TimelineScrubber from './components/TimelineScrubber'
import { AboutPanel } from './features/about'
import { AdvisoryDrawer, AdvisoryPanel, useAdvisories } from './features/advisory'
import { CountdownPanel, useCountdown } from './features/countdown'
import { InfraPanel, infraTooltip, useInfraLayers, useInfraMap } from './features/exposure'
import { HazardPanel, type MapViewMode, StormEdge, useHazardMap } from './features/hazard'
import { ImpactPanel, PathwayCard, useImpactMap } from './features/impact'
import { InsurancePanel, useInsuranceMap } from './features/insurance'
import { RiskCard, RiskPanel, SurgeHeadline, useRiskMap } from './features/risk'
import { LANDFALL_INDEX, REPLAY_TIMESTEPS } from './lib/constants'
import type { Horizon } from './types/contracts'

export default function App() {
  // Replay index into REPLAY_TIMESTEPS; features will read the timestep from here.
  const [timestepIndex, setTimestepIndex] = useState(0)
  // The user's Hazard / Risk choice; null until they pick one (then the view is automatic:
  // Hazard until a block reaches the advisory threshold at this timestep, Risk after).
  const [chosenView, setChosenView] = useState<MapViewMode | null>(null)
  const [map, setMap] = useState<MapLibreMap | null>(null)
  // Now / Next 24 h (v1.3): the user's choice, or null = Next 24 h before landfall (there is
  // nothing ahead to forecast at landfall itself).
  const [chosenHorizon, setChosenHorizon] = useState<Horizon | null>(null)
  const horizon: Horizon = chosenHorizon ?? (timestepIndex < LANDFALL_INDEX ? 24 : 0)

  const infra = useInfraMap()
  const impact = useImpactMap(timestepIndex, infra.state, horizon)
  const risk = useRiskMap(timestepIndex, chosenView, horizon)
  const hazard = useHazardMap(timestepIndex, risk.view, setChosenView, map, horizon, setChosenHorizon)
  const insurance = useInsuranceMap(timestepIndex, risk.view === 'risk')
  const countdown = useCountdown(REPLAY_TIMESTEPS[timestepIndex])
  // Red and orange mean impact only: exposure mutes its colours while impact results show.
  const infraLayers = useInfraLayers(infra, impact.active)

  // Bottom to top: hazard fills or the risk choropleth (one view at a time: both are area
  // fills; in Risk view, gold outlines on blocks with an insurance payout released), muted
  // exposure, impact, the storm track, then the selection highlights.
  const layers = useMemo(
    () => [
      ...hazard.fillLayers,
      ...risk.layers,
      ...insurance.layers,
      ...infraLayers,
      ...impact.layers,
      ...hazard.trackLayers,
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
  const advisory = useAdvisories(timestepIndex, risk.blocks, selectBlock)
  const getTooltip = useCallback(
    (info: PickingInfo) =>
      impactTooltip(info) ?? riskTooltip(info) ?? hazardTooltip(info) ?? infraTooltip(info),
    [impactTooltip, riskTooltip, hazardTooltip],
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

  return (
    <main className="relative h-full w-full overflow-hidden">
      <MapView layers={layers} getTooltip={getTooltip} onClick={onClick} onMapLoad={onMapLoad} />
      <StormEdge {...hazard.edge} />
      <HealthPanel>
        <HazardPanel {...hazard.panel} />
        <SurgeHeadline {...risk.surge} />
        <CountdownPanel state={countdown.state} />
        <InfraPanel
          state={infra.state}
          visible={infra.visible}
          onToggle={infra.toggle}
          muted={impact.active}
        />
        <RiskPanel {...risk.panel} />
        <ImpactPanel {...impact.panel} />
        <InsurancePanel {...insurance.panel} />
        <AdvisoryPanel {...advisory.panel} />
        <AboutPanel />
      </HealthPanel>
      <PathwayCard {...impact.card} />
      <RiskCard {...risk.card} />
      <AdvisoryDrawer {...advisory.drawer} />
      <TimelineScrubber
        index={timestepIndex}
        onChange={setTimestepIndex}
        moments={countdown.moments}
      />
    </main>
  )
}
