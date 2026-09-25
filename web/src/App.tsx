import type { PickingInfo } from '@deck.gl/core'
import { useCallback, useMemo, useState } from 'react'

import HealthPanel from './components/HealthPanel'
import MapView from './components/MapView'
import TimelineScrubber from './components/TimelineScrubber'
import { InfraPanel, infraTooltip, useInfraLayers, useInfraMap } from './features/exposure'
import { ImpactPanel, PathwayCard, useImpactMap } from './features/impact'
import { RiskCard, RiskPanel, useRiskMap } from './features/risk'

export default function App() {
  // Replay index into REPLAY_TIMESTEPS; features will read the timestep from here.
  const [timestepIndex, setTimestepIndex] = useState(0)
  const infra = useInfraMap()
  const impact = useImpactMap(timestepIndex, infra.state)
  // Risk follows the impact panel's synthetic toggle (dev only, DEMO_MODE off).
  const risk = useRiskMap(timestepIndex, impact.panel.synthetic)
  // Red and orange mean impact only: exposure mutes its colours while impact results show.
  const infraLayers = useInfraLayers(infra, impact.active)

  // Bottom to top: muted exposure, risk by block, impact.
  const layers = useMemo(
    () => [...infraLayers, ...risk.layers, ...impact.layers],
    [infraLayers, risk.layers, impact.layers],
  )
  const { tooltip: impactTooltip, onClick: impactClick } = impact
  const { tooltip: riskTooltip, onClick: riskClick, clear: riskClear } = risk
  const getTooltip = useCallback(
    (info: PickingInfo) => impactTooltip(info) ?? riskTooltip(info) ?? infraTooltip(info),
    [impactTooltip, riskTooltip],
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

  return (
    <main className="relative h-full w-full overflow-hidden">
      <MapView
        layers={layers}
        getTooltip={getTooltip}
        onClick={onClick}
        onMapLoad={risk.onMapLoad}
      />
      <HealthPanel>
        <InfraPanel state={infra.state} visible={infra.visible} onToggle={infra.toggle} />
        <RiskPanel {...risk.panel} />
        <ImpactPanel {...impact.panel} />
      </HealthPanel>
      <PathwayCard {...impact.card} />
      <RiskCard {...risk.card} />
      <TimelineScrubber index={timestepIndex} onChange={setTimestepIndex} />
    </main>
  )
}
