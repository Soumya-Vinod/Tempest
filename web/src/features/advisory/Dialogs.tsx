import { useState, type ReactNode } from 'react'

import {
  approverLabel,
  DESIGNATIONS,
  loadApprover,
  saveApprover,
  type Approver,
  type Designation,
} from './useAdvisories'

function Modal({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-slate-900/30">
      <div
        role="dialog"
        aria-label={title}
        className="w-80 rounded-lg bg-white p-4 text-sm text-slate-800 shadow-xl"
      >
        <p className="mb-3 font-medium">{title}</p>
        {children}
      </div>
    </div>
  )
}

function Buttons(props: { ok: string; disabled: boolean; busy: boolean; onCancel: () => void }) {
  return (
    <div className="mt-4 flex justify-end gap-2">
      <button
        type="button"
        onClick={props.onCancel}
        className="rounded px-3 py-1 text-slate-600 hover:bg-slate-100"
      >
        Cancel
      </button>
      <button
        type="submit"
        disabled={props.disabled || props.busy}
        className="rounded bg-violet-700 px-3 py-1 font-medium text-white hover:bg-violet-800 disabled:bg-slate-300"
      >
        {props.busy ? '…' : props.ok}
      </button>
    </div>
  )
}

const INPUT = 'mt-1 w-full rounded border border-slate-300 px-2 py-1'

/** Name plus designation; the last values are remembered in this browser. */
export function ApproveDialog(props: {
  busy: boolean
  error: string | null
  onApprove: (approvedBy: string) => void
  onCancel: () => void
}) {
  const [a, setA] = useState<Approver>(loadApprover)
  const valid = a.name.trim() !== '' && (a.designation !== 'Other' || a.role.trim() !== '')
  return (
    <Modal title="Approve advisory">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (!valid) return
          saveApprover(a)
          props.onApprove(approverLabel(a))
        }}
      >
        <label className="block text-xs text-slate-600">
          Name
          <input
            className={INPUT}
            value={a.name}
            onChange={(e) => setA({ ...a, name: e.target.value })}
            autoFocus
          />
        </label>
        <label className="mt-2 block text-xs text-slate-600">
          Designation
          <select
            className={INPUT}
            value={a.designation}
            onChange={(e) => setA({ ...a, designation: e.target.value as Designation })}
          >
            {DESIGNATIONS.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </label>
        {a.designation === 'Other' && (
          <label className="mt-2 block text-xs text-slate-600">
            Role
            <input
              className={INPUT}
              value={a.role}
              onChange={(e) => setA({ ...a, role: e.target.value })}
            />
          </label>
        )}
        {valid && <p className="mt-2 text-xs text-slate-500">Recorded as: {approverLabel(a)}</p>}
        {props.error && <p className="mt-2 text-xs text-red-600">{props.error}</p>}
        <Buttons ok="Approve" disabled={!valid} busy={props.busy} onCancel={props.onCancel} />
      </form>
    </Modal>
  )
}

export function RejectDialog(props: {
  busy: boolean
  error: string | null
  onReject: (reason: string) => void
  onCancel: () => void
}) {
  const [reason, setReason] = useState('')
  return (
    <Modal title="Reject advisory">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (reason.trim()) props.onReject(reason.trim())
        }}
      >
        <label className="block text-xs text-slate-600">
          Reason (required)
          <textarea
            className={`${INPUT} h-20`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            autoFocus
          />
        </label>
        {props.error && <p className="mt-2 text-xs text-red-600">{props.error}</p>}
        <Buttons
          ok="Reject"
          disabled={!reason.trim()}
          busy={props.busy}
          onCancel={props.onCancel}
        />
      </form>
    </Modal>
  )
}
