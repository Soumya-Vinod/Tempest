import { type KeyboardEvent, type ReactNode, useId, useRef, useState } from 'react'

import Deferred from './Deferred'

export type TabId = 'act' | 'situation' | 'finance' | 'layers'

export interface PanelTab {
  id: TabId
  label: string
  /** A small count after the label (e.g. facilities to act on); hidden when 0 or undefined. */
  badge?: number
  content: ReactNode
}

const STORAGE_KEY = 'tempest.panelTab'
const IDS: readonly TabId[] = ['act', 'situation', 'finance', 'layers']

/** The tab the user last picked, if storage works and holds a valid one. */
function storedTab(): TabId | null {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY)
    return IDS.includes(v as TabId) ? (v as TabId) : null
  } catch {
    return null
  }
}

function storeTab(id: TabId) {
  try {
    window.localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // Private mode or blocked storage: the choice just isn't remembered.
  }
}

/**
 * The side panel's tabs. Until the user picks one, `automatic` decides (Act once anything is
 * expected to be cut off); a pick is remembered across reloads. A tab mounts when first shown
 * (its lazy panels load then) and stays mounted (hidden), so lists keep their expanded state.
 */
export default function PanelTabs({ tabs, automatic }: { tabs: PanelTab[]; automatic: TabId }) {
  const [chosen, setChosen] = useState<TabId | null>(storedTab)
  const active = chosen ?? automatic
  const base = useId()
  const buttons = useRef<(HTMLButtonElement | null)[]>([])

  const pick = (id: TabId) => {
    setChosen(id)
    storeTab(id)
  }
  // Arrow keys move between tabs (WAI-ARIA tabs pattern, automatic activation).
  const onKeyDown = (e: KeyboardEvent, i: number) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const next = (i + step + tabs.length) % tabs.length
    pick(tabs[next].id)
    buttons.current[next]?.focus()
  }

  return (
    <>
      <div
        role="tablist"
        aria-label="Panel sections"
        className="sticky top-0 z-10 -mx-4 mb-3 flex gap-1 border-b border-slate-200 bg-white px-4 pt-1"
      >
        {tabs.map((t, i) => {
          const selected = t.id === active
          return (
            <button
              key={t.id}
              ref={(el) => {
                buttons.current[i] = el
              }}
              type="button"
              role="tab"
              id={`${base}-tab-${t.id}`}
              aria-selected={selected}
              aria-controls={`${base}-panel-${t.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => pick(t.id)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={`-mb-px flex items-center gap-1 border-b-2 px-2 py-1.5 text-xs font-semibold whitespace-nowrap ${
                selected
                  ? 'border-violet-700 text-violet-800'
                  : 'border-transparent text-slate-500 hover:text-slate-800'
              }`}
            >
              {t.label}
              {!!t.badge && (
                <span className="rounded-full bg-red-100 px-1.5 text-[10px] text-red-800 tabular-nums">
                  {t.badge}
                </span>
              )}
            </button>
          )
        })}
      </div>
      {tabs.map((t) => (
        <div
          key={t.id}
          role="tabpanel"
          id={`${base}-panel-${t.id}`}
          aria-labelledby={`${base}-tab-${t.id}`}
          hidden={t.id !== active}
          className="[&>*:first-child]:mt-0"
        >
          <Deferred
            when={t.id === active}
            fallback={<p className="text-xs text-slate-500">Loading section…</p>}
          >
            {t.content}
          </Deferred>
        </div>
      ))}
    </>
  )
}
