import { useEffect, useState, type ReactNode } from 'react'

import { getHealth, type HealthResponse } from '../lib/api'
import { ABOVE_TIMELINE, PANEL_WIDTH, UI_GAP } from '../lib/layout'

const POLL_MS = 15_000
// Earth Engine runs offline (its results are committed as fixtures), so in DEMO_MODE these keys
// are listed as not needed and left out of the count.
const OFFLINE_KEYS = new Set(['gee_service_account', 'gee_key_path'])

type HealthState =
  | { kind: 'loading' }
  | { kind: 'ok'; data: HealthResponse }
  | { kind: 'error'; message: string }

/** "● Healthy · DEMO MODE · Keys 8/10 ▸": one line that expands into the per-key list. */
function BackendStatus({ health }: { health: HealthState }) {
  const [open, setOpen] = useState(false)
  if (health.kind === 'loading') return <span className="text-xs text-slate-500">Checking…</span>
  if (health.kind === 'error') {
    return (
      <span className="text-xs text-red-700" title={health.message}>
        ● Backend unreachable
      </span>
    )
  }
  const keys = Object.entries(health.data.configured)
  const unused = (key: string) => health.data.demo_mode && OFFLINE_KEYS.has(key)
  const counted = keys.filter(([key]) => !unused(key))
  const set = counted.filter(([, ok]) => ok).length
  return (
    <div className="text-right">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Backend status and configured keys"
        className="text-xs text-slate-600 hover:text-slate-900"
      >
        <span className="text-emerald-500">●</span> Healthy ·{' '}
        <span className={health.data.demo_mode ? 'text-amber-700' : 'text-sky-700'}>
          {health.data.demo_mode ? 'DEMO MODE' : 'LIVE'}
        </span>{' '}
        · Keys {set}/{counted.length} {open ? '▾' : '▸'}
      </button>
      {open && (
        <ul className="mt-1 space-y-1 text-left">
          {keys.map(([key, ok]) => (
            <li key={key} className="flex justify-between font-mono text-xs">
              <span>{key}</span>
              {unused(key) ? (
                <span className="text-slate-400">— not needed in demo</span>
              ) : (
                <span className={ok ? 'text-emerald-600' : 'text-slate-400'}>
                  {ok ? '✓ set' : '✗ not set'}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Side panel: a slim header (name, one-line backend status), then the feature sections. */
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
      className="absolute z-20 overflow-y-auto rounded-lg bg-white p-4 text-sm text-slate-800 shadow-lg"
      style={{ top: UI_GAP, right: UI_GAP, bottom: ABOVE_TIMELINE, width: PANEL_WIDTH }}
    >
      <header className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-slate-100 pb-2">
        <h1 className="text-base leading-5 font-semibold">Tempest</h1>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide whitespace-nowrap text-slate-600">
          REPLAY · Amphan 2020 · South 24 Parganas
        </span>
        <div className="ml-auto">
          <BackendStatus health={health} />
        </div>
      </header>
      {children}
    </aside>
  )
}
