import { useState } from 'react'

import HealthPanel from './components/HealthPanel'
import MapView from './components/MapView'
import TimelineScrubber from './components/TimelineScrubber'
import { InfraPanel, infraTooltip, useInfraMap } from './features/exposure'

export default function App() {
  // Replay index into REPLAY_TIMESTEPS; features will read the timestep from here.
  const [timestepIndex, setTimestepIndex] = useState(0)
  const infra = useInfraMap()

  return (
    <main className="relative h-full w-full overflow-hidden">
      <MapView layers={infra.layers} getTooltip={infraTooltip} />
      <HealthPanel>
        <InfraPanel state={infra.state} visible={infra.visible} onToggle={infra.toggle} />
      </HealthPanel>
      <TimelineScrubber index={timestepIndex} onChange={setTimestepIndex} />
    </main>
  )
}
