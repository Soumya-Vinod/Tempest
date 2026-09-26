import { useState } from 'react'

import {
  approveAdvisory,
  getAdvisory,
  newDraftFrom,
  rejectAdvisory,
  updateAdvisory,
} from '../../lib/api'
import type { Advisory, AdvisoryText, Citation, Language } from '../../types/contracts'
import { DispatchDialog, ReceiptList } from '../dispatch'
import { ApproveDialog, RejectDialog } from './Dialogs'
import { errorText } from './errors'
import { STATUS_STYLE, timestepLabel } from './style'
import { useAudit } from './useAdvisories'

const LANGUAGES: { id: Language; label: string }[] = [
  { id: 'en', label: 'English' },
  { id: 'bn', label: 'বাংলা' },
  { id: 'hi', label: 'हिन्दी' },
]

/** Wind in km/h to the nearest 5, as the advisory text states it (api render.py). */
const KMH_STEP = 5

function citationValue(c: Citation): string {
  if (typeof c.value !== 'number') return c.value
  const text = `${c.value}${c.unit ? ` ${c.unit}` : ''}`
  if (c.unit !== 'm/s') return text
  const kmh = Math.floor((c.value * 3.6) / KMH_STEP + 0.5) * KMH_STEP
  return `${text} (${kmh} km/h)`
}

function Text({ t }: { t: AdvisoryText }) {
  return (
    <div className="space-y-2">
      <p className="font-semibold">{t.headline}</p>
      <p className="whitespace-pre-wrap">{t.body}</p>
      <ol className="list-decimal space-y-1 pl-5">
        {t.actions.map((a, i) => (
          <li key={i}>{a}</li>
        ))}
      </ol>
    </div>
  )
}

const FIELD = 'w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs'

function Editor(props: {
  value: AdvisoryText
  onChange: (t: AdvisoryText) => void
}) {
  const t = props.value
  const setAction = (i: number, a: string) =>
    props.onChange({ ...t, actions: t.actions.map((x, j) => (j === i ? a : x)) })
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-slate-500">
        Keep every {'{{key}}'} placeholder; write no figures or number words yourself. The
        exercise label is added to the body automatically.
      </p>
      <input
        className={FIELD}
        value={t.headline}
        onChange={(e) => props.onChange({ ...t, headline: e.target.value })}
        aria-label="Headline"
      />
      <textarea
        className={`${FIELD} h-28`}
        value={t.body}
        onChange={(e) => props.onChange({ ...t, body: e.target.value })}
        aria-label="Body"
      />
      {t.actions.map((a, i) => (
        <div key={i} className="flex gap-1">
          <textarea
            className={`${FIELD} h-12`}
            value={a}
            onChange={(e) => setAction(i, e.target.value)}
            aria-label={`Action ${i + 1}`}
          />
          {t.actions.length > 3 && (
            <button
              type="button"
              onClick={() => props.onChange({ ...t, actions: t.actions.filter((_, j) => j !== i) })}
              className="px-1 text-slate-400 hover:text-red-600"
              aria-label={`Remove action ${i + 1}`}
            >
              ×
            </button>
          )}
        </div>
      ))}
      {t.actions.length < 5 && (
        <button
          type="button"
          onClick={() => props.onChange({ ...t, actions: [...t.actions, ''] })}
          className="text-xs text-violet-700 hover:underline"
        >
          + Add action
        </button>
      )}
    </div>
  )
}

const BUTTON = 'rounded border px-2 py-1 text-xs font-medium disabled:opacity-50'

/** One advisory: language tabs, citations, the approval actions and the audit trail. */
export default function AdvisoryDetail(props: {
  advisory: Advisory
  onChanged: (a: Advisory) => void
  onBack: () => void
}) {
  const p = props.advisory.properties
  const [language, setLanguage] = useState<Language>('en')
  const [editing, setEditing] = useState<AdvisoryText | null>(null)
  const [dialog, setDialog] = useState<'approve' | 'reject' | 'dispatch' | null>(null)
  const [dispatches, setDispatches] = useState(0) // bumps the receipt list after a dispatch
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const version = `${p.status}|${JSON.stringify(p.templates)}|${dispatches}`
  const audit = useAudit(p.id, version)

  const run = async (action: () => Promise<Advisory>, after?: () => void) => {
    setBusy(true)
    setError(null)
    try {
      props.onChanged(await action())
      after?.()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const isDraft = p.status === 'draft'
  return (
    <div>
      <button type="button" onClick={props.onBack} className="text-xs text-violet-700">
        ← Queue
      </button>
      <div className="mt-1 flex items-center gap-2">
        <p className="font-medium">{p.block_name}</p>
        <span className="text-xs text-slate-500">{timestepLabel(p.timestep)}</span>
        <span className={`ml-auto rounded px-2 py-0.5 text-xs ${STATUS_STYLE[p.status]}`}>
          {p.status}
        </span>
      </div>
      {p.approved_by && (
        <p className="text-xs text-slate-500">Approved by {p.approved_by}</p>
      )}
      {p.rejection_reason && (
        <p className="text-xs text-slate-500">Rejected: {p.rejection_reason}</p>
      )}

      <div className="mt-3 flex gap-1 border-b border-slate-200" role="tablist">
        {LANGUAGES.map((l) => (
          <button
            key={l.id}
            type="button"
            role="tab"
            aria-selected={language === l.id}
            disabled={editing !== null && language !== l.id}
            onClick={() => setLanguage(l.id)}
            className={`px-3 py-1 text-xs ${
              language === l.id
                ? 'border-b-2 border-violet-700 font-semibold text-violet-800'
                : 'text-slate-500 disabled:opacity-40'
            }`}
          >
            {l.label}
          </button>
        ))}
      </div>
      <div className="mt-3 text-sm leading-relaxed">
        {editing ? (
          <Editor value={editing} onChange={setEditing} />
        ) : (
          <Text t={p.texts[language]} />
        )}
      </div>

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {isDraft && editing && (
          <>
            <button
              type="button"
              disabled={busy}
              className={`${BUTTON} border-violet-700 bg-violet-700 text-white`}
              onClick={() =>
                run(
                  () => updateAdvisory(p.id, { templates: { ...p.templates, [language]: editing } }),
                  () => setEditing(null),
                )
              }
            >
              Save
            </button>
            <button
              type="button"
              className={`${BUTTON} border-slate-300`}
              onClick={() => {
                setEditing(null)
                setError(null)
              }}
            >
              Cancel
            </button>
          </>
        )}
        {isDraft && !editing && (
          <>
            <button
              type="button"
              className={`${BUTTON} border-slate-300`}
              onClick={() => setEditing(p.templates[language])}
            >
              Edit {LANGUAGES.find((l) => l.id === language)?.label}
            </button>
            <button
              type="button"
              className={`${BUTTON} border-emerald-600 bg-emerald-600 text-white`}
              onClick={() => setDialog('approve')}
            >
              Approve
            </button>
            <button
              type="button"
              className={`${BUTTON} border-red-300 text-red-700`}
              onClick={() => setDialog('reject')}
            >
              Reject
            </button>
          </>
        )}
        {(p.status === 'approved' || p.status === 'sent') && (
          <button
            type="button"
            disabled={busy}
            className={`${BUTTON} border-violet-700 bg-violet-700 text-white`}
            onClick={() => setDialog('dispatch')}
          >
            {p.status === 'sent' ? 'Resend' : 'Dispatch'}
          </button>
        )}
        {!isDraft && (
          <button
            type="button"
            disabled={busy}
            className={`${BUTTON} border-slate-300`}
            onClick={() => run(() => newDraftFrom(p.id))}
          >
            New draft from this
          </button>
        )}
      </div>

      <h3 className="mt-4 text-xs font-semibold tracking-wide text-slate-500 uppercase">
        Where the figures come from
      </h3>
      <table className="mt-1 w-full text-xs">
        <tbody>
          {p.citations.map((c) => (
            <tr key={c.key} className="border-t border-slate-100 align-top">
              <td className="py-0.5 pr-2 text-slate-600" title={`{{${c.key}}}`}>
                {c.label}
              </td>
              <td className="py-0.5 pr-2">{citationValue(c)}</td>
              <td className="py-0.5 text-slate-400">{c.source}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {(p.status === 'approved' || p.status === 'sent') && (
        <ReceiptList advisoryId={p.id} version={`${p.status}|${dispatches}`} />
      )}

      <h3 className="mt-4 text-xs font-semibold tracking-wide text-slate-500 uppercase">Audit</h3>
      <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
        {audit.map((e) => (
          <li key={e.id}>
            <span className="tabular-nums text-slate-400">
              {e.at.slice(0, 16).replace('T', ' ')}
            </span>{' '}
            {e.action.replace(/_/g, ' ')}
            {e.actor && <> · {e.actor}</>}
          </li>
        ))}
      </ul>

      {dialog === 'approve' && (
        <ApproveDialog
          busy={busy}
          error={error}
          onCancel={() => {
            setDialog(null)
            setError(null)
          }}
          onApprove={(approvedBy) =>
            run(() => approveAdvisory(p.id, { approved_by: approvedBy }), () => setDialog(null))
          }
        />
      )}
      {dialog === 'dispatch' && (
        <DispatchDialog
          advisoryId={p.id}
          blockName={p.block_name}
          resend={p.status === 'sent'}
          onClose={(dispatched) => {
            setDialog(null)
            if (dispatched) {
              setDispatches((n) => n + 1)
              void run(() => getAdvisory(p.id))
            }
          }}
        />
      )}
      {dialog === 'reject' && (
        <RejectDialog
          busy={busy}
          error={error}
          onCancel={() => {
            setDialog(null)
            setError(null)
          }}
          onReject={(reason) =>
            run(() => rejectAdvisory(p.id, { reason }), () => setDialog(null))
          }
        />
      )}
    </div>
  )
}
