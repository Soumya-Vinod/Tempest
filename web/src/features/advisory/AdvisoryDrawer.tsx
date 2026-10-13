import { useState } from 'react'

import { PANEL_WIDTH, useLayout } from '../../lib/layout'
import { useTimeline } from '../../lib/timeline'
import type { Advisory, AdvisoryStatus } from '../../types/contracts'
import AdvisoryDetail from './AdvisoryDetail'
import { CHIP, STATUS_LABEL, STATUS_STYLE, timestepLabel } from './style'
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
  const timeline = useTimeline()
  const [filter, setFilter] = useState<AdvisoryStatus | 'all'>('draft')
  const { aboveTimeline, gap, phone } = useLayout()
  if (!props.open) return null
  const all = props.queue.status === 'ok' ? props.queue.data : []
  const selected = all.find((a) => a.id === props.selectedId) ?? null
  const shown = filter === 'all' ? all : all.filter((a) => a.properties.status === filter)

  return (
    <aside
      className={`absolute overflow-y-auto rounded-lg bg-white p-4 text-sm text-slate-800 shadow-lg ${
        phone ? 'z-40' : 'z-20'
      }`}
      // Phones: over everything (the sheet too), until it is closed.
      style={
        phone
          ? { top: gap, right: gap, bottom: gap, left: gap }
          : { top: gap, right: 2 * gap + PANEL_WIDTH, bottom: aboveTimeline, width: DRAWER_WIDTH }
      }
      aria-label="Advisory queue"
    >
      <div className="mb-2 flex items-center">
        <h2 className="text-title font-semibold text-ink">
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
                  filter === f.id ? 'bg-accent-wash text-accent' : 'text-ink-subtle hover:text-ink'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          {props.queue.status === 'loading' && <p className="text-xs text-slate-500">Loading…</p>}
          {props.queue.status === 'error' && (
            <p className="text-xs text-sev-cut">{props.queue.message}</p>
          )}
          {props.queue.status === 'ok' && shown.length === 0 && (
            <p className="text-xs text-ink-subtle">No advisories here yet.</p>
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
                      <span className="text-xs text-slate-500">{timestepLabel(timeline, p.timestep)}</span>
                      <span className={`ml-auto ${CHIP} ${STATUS_STYLE[p.status]}`}>
                        {STATUS_LABEL[p.status]}
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
