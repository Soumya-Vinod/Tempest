import { useEffect, useRef, useState, type ReactNode } from 'react'

import { getHealth, type HealthResponse } from '../lib/api'
import { PANEL_WIDTH, UI_GAP, useLayout } from '../lib/layout'

const POLL_MS = 15_000

type HealthState =
  | { kind: 'loading' }
  | { kind: 'ok'; data: HealthResponse }
  | { kind: 'error'; message: string }

/**
 * The configured keys (/health), grouped into the services they enable. Earth Engine is not
 * listed: it runs offline and its results are committed as fixtures.
 */
const SERVICES: { name: string; ready: (k: Record<string, boolean>) => boolean }[] = [
  { name: 'AI drafting (Gemini, Groq fallback)', ready: (k) => !!(k.gemini_api_key || k.groq_api_key) },
  { name: 'Telegram alerts', ready: (k) => !!(k.telegram_bot_token && k.telegram_chat_id) },
  {
    name: 'Email alerts',
    ready: (k) =>
      !!(k.dispatch_email_to && ((k.gmail_address && k.gmail_app_password) || k.brevo_api_key)),
  },
  { name: 'Dispatch PIN', ready: (k) => !!k.dispatch_pin },
]

/**
 * "● Replay mode · all services connected ▸": one plain line that expands into the services;
 * the raw key names are in its tooltip.
 */
function BackendStatus({ health }: { health: HealthState }) {
  const [open, setOpen] = useState(false)
  if (health.kind === 'loading') return <span className="text-xs text-slate-500">Connecting…</span>
  if (health.kind === 'error') {
    return (
      <span className="text-xs text-red-700" title={health.message}>
        ● Can&apos;t reach the server
      </span>
    )
  }
  const keys = health.data.configured
  const services = SERVICES.map((s) => ({ name: s.name, ready: s.ready(keys) }))
  const ready = services.filter((s) => s.ready).length
  const mode = health.data.demo_mode ? 'Replay mode' : 'Live mode'
  const summary =
    ready === services.length
      ? 'all services connected'
      : `${ready} of ${services.length} services connected`
  const details = Object.entries(keys)
    .map(([key, ok]) => `${key}: ${ok ? 'set' : 'not set'}`)
    .join('\n')
  const what = health.data.demo_mode ? 'replaying Cyclone Amphan from stored data' : 'live data'
  return (
    <div className="text-right">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title={`${mode}: ${what}.\n${details}`}
        className="text-xs text-slate-600 hover:text-slate-900"
      >
        <span className={ready === services.length ? 'text-emerald-500' : 'text-amber-500'}>●</span>{' '}
        {mode} · {summary} {open ? '▾' : '▸'}
      </button>
      {open && (
        <ul className="mt-1 space-y-1 text-left">
          {services.map((s) => (
            <li key={s.name} className="flex justify-between gap-2 text-xs">
              <span>{s.name}</span>
              <span className={s.ready ? 'text-emerald-700' : 'text-slate-500'}>
                {s.ready ? '✓ connected' : '— not set up'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** More content below the scroll position (a fade hints at it); re-checked as content changes. */
function useMoreBelow() {
  const ref = useRef<HTMLDivElement>(null)
  const [more, setMore] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    // At most one layout read per frame, however many mutations land in it.
    let frame = 0
    const check = () => {
      if (frame) return
      frame = requestAnimationFrame(() => {
        frame = 0
        setMore(el.scrollTop + el.clientHeight < el.scrollHeight - 4)
      })
    }
    check()
    el.addEventListener('scroll', check, { passive: true })
    const resize = new ResizeObserver(check)
    resize.observe(el)
    const mutations = new MutationObserver(check)
    mutations.observe(el, { childList: true, subtree: true })
    return () => {
      cancelAnimationFrame(frame)
      el.removeEventListener('scroll', check)
      resize.disconnect()
      mutations.disconnect()
    }
  }, [])
  return { ref, more }
}

/** Side panel: a slim header (name, one-line backend status), then the feature sections. */
export default function HealthPanel({ children }: { children?: ReactNode }) {
  const [health, setHealth] = useState<HealthState>({ kind: 'loading' })
  const { ref: scrollRef, more } = useMoreBelow()
  const { aboveTimeline } = useLayout()

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
      className="absolute z-20 overflow-hidden rounded-lg bg-white text-sm text-slate-800 shadow-lg"
      style={{ top: UI_GAP, right: UI_GAP, bottom: aboveTimeline, width: PANEL_WIDTH }}
    >
      <div ref={scrollRef} className="h-full overflow-y-auto p-4 pb-8">
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
      </div>
      {/* Content continues below: fade the cut edge instead of slicing text in half. */}
      <div
        className={`pointer-events-none absolute inset-x-0 bottom-0 h-10 rounded-b-lg bg-linear-to-t from-white to-transparent transition-opacity ${
          more ? 'opacity-100' : 'opacity-0'
        }`}
        aria-hidden
      />
    </aside>
  )
}
