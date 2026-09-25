import { useEffect, useState, type ReactNode } from 'react'

import { getHealth, type HealthResponse } from '../lib/api'
import { ABOVE_TIMELINE, PANEL_WIDTH, UI_GAP } from '../lib/layout'

const POLL_MS = 15_000

type HealthState =
  | { kind: 'loading' }
  | { kind: 'ok'; data: HealthResponse }
  | { kind: 'error'; message: string }

/** One line ("Keys: 2/6 configured ▸") that expands into the per-key list. Values never shown. */
function ConfiguredKeys({ configured }: { configured: Record<string, boolean> }) {
  const [open, setOpen] = useState(false)
  const keys = Object.entries(configured)
  const set = keys.filter(([, ok]) => ok).length
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="text-xs text-slate-500 hover:text-slate-800"
      >
        Keys: {set}/{keys.length} configured {open ? '▾' : '▸'}
      </button>
      {open && (
        <ul className="mt-1 space-y-1">
          {keys.map(([key, ok]) => (
            <li key={key} className="flex justify-between font-mono text-xs">
              <span>{key}</span>
              <span className={ok ? 'text-emerald-600' : 'text-slate-400'}>
                {ok ? '✓ set' : '✗ not set'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

/** Side panel: backend status, then feature sections passed as children. */
export default function HealthPanel({ children }: { children?: ReactNode }) {
  const [health, setHealth] = useState<HealthState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const data = await getHealth()
        if (!cancelled) setHealth({ kind: 'ok', data })
      } catch (err) {
        if (!cancelled) setHealth({ kind: 'error', message: (err as Error).message })
      }
    }
    void poll()
    const id = setInterval(() => void poll(), POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return (
    <aside
      className="absolute overflow-y-auto rounded-lg bg-white p-4 text-sm text-slate-800 shadow-lg"
      style={{ top: UI_GAP, right: UI_GAP, bottom: ABOVE_TIMELINE, width: PANEL_WIDTH }}
    >
      <h1 className="text-base font-semibold">Tempest</h1>
      <p className="mb-4 text-xs text-slate-500">Cyclone Amphan replay · South 24 Parganas</p>

      <h2 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">Backend</h2>
      {health.kind === 'loading' && <p className="text-slate-500">Checking…</p>}
      {health.kind === 'error' && (
        <p className="text-red-700">
          <span className="font-medium">Unreachable</span>
          <span className="block text-xs text-red-600">{health.message}</span>
        </p>
      )}
      {health.kind === 'ok' && (
        <>
          <div className="mb-3 flex items-center gap-2">
            <span className="size-2 rounded-full bg-emerald-500" aria-hidden />
            <span className="font-medium">Healthy</span>
            <span
              className={`ml-auto rounded px-2 py-0.5 text-xs font-semibold ${
                health.data.demo_mode ? 'bg-amber-100 text-amber-800' : 'bg-sky-100 text-sky-800'
              }`}
            >
              {health.data.demo_mode ? 'DEMO MODE' : 'LIVE'}
            </span>
          </div>
          <ConfiguredKeys configured={health.data.configured} />
        </>
      )}
      {children}
    </aside>
  )
}
