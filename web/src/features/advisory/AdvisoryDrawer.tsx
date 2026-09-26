import { useState } from 'react'

import { ABOVE_TIMELINE, PANEL_WIDTH, UI_GAP } from '../../lib/layout'
import type { Advisory, AdvisoryStatus } from '../../types/contracts'
import AdvisoryDetail from './AdvisoryDetail'
import { STATUS_STYLE, timestepLabel } from './style'
import type { Loadable } from './useAdvisories'

const DRAWER_WIDTH = 420
const FILTERS: { id: AdvisoryStatus | 'all'; label: string }[] = [
  { id: 'draft', label: 'Drafts' },
  { id: 'approved', label: 'Approved' },
  { id: 'rejected', label: 'Rejected' },
  { id: 'all', label: 'All' },
]

export interface AdvisoryDrawerProps {
  open: boolean
  queue: Loadable<Advisory[]>
  selectedId: string | null
  onSelect: (advisory: Advisory | null) => void
  onChanged: (advisory: Advisory) => void
  onClose: () => void
}

/** The approval queue, beside the side panel: a list, or one advisory's detail. */
export default function AdvisoryDrawer(props: AdvisoryDrawerProps) {
  const [filter, setFilter] = useState<AdvisoryStatus | 'all'>('draft')
  if (!props.open) return null
  const all = props.queue.status === 'ok' ? props.queue.data : []
  const selected = all.find((a) => a.id === props.selectedId) ?? null
  const shown = filter === 'all' ? all : all.filter((a) => a.properties.status === filter)

  return (
    <aside
      className="absolute overflow-y-auto rounded-lg bg-white p-4 text-sm text-slate-800 shadow-lg"
      style={{
        top: UI_GAP,
        right: 2 * UI_GAP + PANEL_WIDTH,
        bottom: ABOVE_TIMELINE,
        width: DRAWER_WIDTH,
      }}
      aria-label="Advisory queue"
    >
      <div className="mb-2 flex items-center">
        <h2 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
          Advisory queue
        </h2>
        <button
          type="button"
          onClick={props.onClose}
          className="-mt-1 ml-auto px-1 text-lg leading-none text-slate-400 hover:text-slate-700"
          aria-label="Close advisory queue"
        >
          ×
        </button>
      </div>

      {selected ? (
        <AdvisoryDetail
          key={selected.id}
          advisory={selected}
          onChanged={props.onChanged}
          onBack={() => props.onSelect(null)}
        />
      ) : (
        <>
          <div className="mb-2 flex gap-1">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilter(f.id)}
                className={`rounded px-2 py-0.5 text-xs ${
                  filter === f.id ? 'bg-violet-100 text-violet-800' : 'text-slate-500'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          {props.queue.status === 'loading' && <p className="text-xs text-slate-500">Loading…</p>}
          {props.queue.status === 'error' && (
            <p className="text-xs text-red-600">{props.queue.message}</p>
          )}
          {props.queue.status === 'ok' && shown.length === 0 && (
            <p className="text-xs text-slate-500">Nothing here yet.</p>
          )}
          <ul className="divide-y divide-slate-100">
            {shown.map((a) => {
              const p = a.properties
              return (
                <li key={a.id}>
                  <button
                    type="button"
                    onClick={() => props.onSelect(a)}
                    className="w-full py-2 text-left hover:bg-slate-50"
                  >
                    <span className="flex items-center gap-2">
                      <span className="font-medium">{p.block_name}</span>
                      <span className="text-xs text-slate-500">{timestepLabel(p.timestep)}</span>
                      <span className={`ml-auto rounded px-2 py-0.5 text-xs ${STATUS_STYLE[p.status]}`}>
                        {p.status}
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-slate-600">
                      {p.texts.en.headline}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </aside>
  )
}
