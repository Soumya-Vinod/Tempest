import { useState } from 'react'

import HealthPanel from './components/HealthPanel'
import MapView from './components/MapView'
import TimelineScrubber from './components/TimelineScrubber'

export default function App() {
  // Replay index into REPLAY_TIMESTEPS; features will read the timestep from here.
  const [timestepIndex, setTimestepIndex] = useState(0)

  return (
    <main className="relative h-full w-full overflow-hidden">
      <MapView />
      <HealthPanel />
      <TimelineScrubber index={timestepIndex} onChange={setTimestepIndex} />
    </main>
  )
}
