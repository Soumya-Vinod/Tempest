import type { PickingInfo } from '@deck.gl/core'
import { useCallback, useMemo, useState } from 'react'

import HealthPanel from './components/HealthPanel'
import MapView from './components/MapView'
import TimelineScrubber from './components/TimelineScrubber'
import { InfraPanel, infraTooltip, useInfraLayers, useInfraMap } from './features/exposure'
import { ImpactPanel, PathwayCard, useImpactMap } from './features/impact'

export default function App() {
  // Replay index into REPLAY_TIMESTEPS; features will read the timestep from here.
  const [timestepIndex, setTimestepIndex] = useState(0)
  const infra = useInfraMap()
  const impact = useImpactMap(timestepIndex, infra.state)
  // Red and orange mean impact only: exposure mutes its colours while impact results show.
  const infraLayers = useInfraLayers(infra, impact.active)

  // Impact layers sit above the exposure layers.
  const layers = useMemo(() => [...infraLayers, ...impact.layers], [infraLayers, impact.layers])
  const { tooltip: impactTooltip } = impact
  const getTooltip = useCallback(
    (info: PickingInfo) => impactTooltip(info) ?? infraTooltip(info),
    [impactTooltip],
  )

  return (
    <main className="relative h-full w-full overflow-hidden">
      <MapView layers={layers} getTooltip={getTooltip} onClick={impact.onClick} />
      <HealthPanel>
        <InfraPanel state={infra.state} visible={infra.visible} onToggle={infra.toggle} />
        <ImpactPanel {...impact.panel} />
      </HealthPanel>
      <PathwayCard {...impact.card} />
      <TimelineScrubber index={timestepIndex} onChange={setTimestepIndex} />
    </main>
  )
}
