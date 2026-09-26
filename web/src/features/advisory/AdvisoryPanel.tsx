import { useState } from 'react'

import type { AdvisorySuggestions, BlockId } from '../../types/contracts'
import type { Loadable } from './useAdvisories'

export interface AdvisoryPanelProps {
  timestepLabel: string
  suggestions: Loadable<AdvisorySuggestions>
  /** Every scored block, for adding one that isn't suggested. */
  blocks: { block_id: BlockId; block_name: string }[]
  generating: BlockId | null
  error: string | null
  drafts: number
  approved: number
  onGenerate: (blockId: BlockId) => void
  onOpenQueue: () => void
}

function GenerateButton(props: { busy: boolean; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className="ml-auto rounded bg-violet-700 px-2 py-0.5 text-xs font-medium text-white hover:bg-violet-800 disabled:bg-slate-300"
    >
      {props.busy ? 'Generating…' : 'Generate'}
    </button>
  )
}

/** "Advisories" side-panel section: suggested blocks for this timestep, any other block, queue. */
export default function AdvisoryPanel(props: AdvisoryPanelProps) {
  const { suggestions, generating } = props
  const [other, setOther] = useState('')
  const suggested = suggestions.status === 'ok' ? suggestions.data.blocks : []
  const others = props.blocks
    .filter((b) => !suggested.some((s) => s.block_id === b.block_id))
    .sort((a, b) => a.block_name.localeCompare(b.block_name))

  return (
    <section className="mt-5">
      <h2 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
        Advisories
      </h2>
      {suggestions.status === 'loading' && <p className="text-xs text-slate-500">Loading…</p>}
      {suggestions.status === 'error' && (
        <p className="text-xs text-slate-500">Suggestions unavailable: {suggestions.message}</p>
      )}
      {suggestions.status === 'ok' && (
        <>
          <p className="text-[11px] text-slate-500">
            Suggested at {props.timestepLabel}: risk score ≥{' '}
            {suggestions.data.threshold.toFixed(2)}
          </p>
          {suggested.length === 0 && (
            <p className="mt-1 text-xs text-slate-500">No block at or above the threshold.</p>
          )}
          <ul className="mt-1 space-y-1">
            {suggested.map((b) => (
              <li key={b.block_id} className="flex items-center gap-2 text-xs">
                <span>{b.block_name}</span>
                <span className="text-slate-500 tabular-nums">{b.score.toFixed(2)}</span>
                <GenerateButton
                  busy={generating === b.block_id}
                  disabled={generating !== null}
                  onClick={() => props.onGenerate(b.block_id)}
                />
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="mt-2 flex items-center gap-2 text-xs">
        <select
          value={other}
          onChange={(e) => setOther(e.target.value)}
          className="min-w-0 flex-1 rounded border border-slate-300 px-1 py-0.5"
          aria-label="Another block"
        >
          <option value="">Add another block…</option>
          {others.map((b) => (
            <option key={b.block_id} value={b.block_id}>
              {b.block_name}
            </option>
          ))}
        </select>
        <GenerateButton
          busy={generating !== null && generating === other}
          disabled={!other || generating !== null}
          onClick={() => props.onGenerate(other)}
        />
      </div>
      {props.error && <p className="mt-1 text-xs text-red-600">{props.error}</p>}
      <button
        type="button"
        onClick={props.onOpenQueue}
        className="mt-2 text-xs text-violet-700 hover:underline"
      >
        Open queue ({props.drafts} draft{props.drafts === 1 ? '' : 's'}, {props.approved} approved)
      </button>
    </section>
  )
}
