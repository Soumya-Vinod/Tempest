import { UI_GAP } from '../lib/layout'
import { useApiStatus } from '../lib/useApiStatus'

/** Shown while the first API request has had no answer for 3 s: the free API instance is
 *  probably starting up (about a minute after a spin-down; deploy.md). */
export default function WakingNotice() {
  const { waking } = useApiStatus()
  if (!waking) return null
  return (
    <div
      role="status"
      className="absolute left-1/2 z-30 -translate-x-1/2 rounded-full bg-slate-800 px-3 py-1 text-xs text-white shadow-lg"
      style={{ top: UI_GAP }}
    >
      Waking up the server…
    </div>
  )
}
