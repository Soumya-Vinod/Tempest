import { useState } from 'react'

import { dispatchAdvisory } from '../../lib/api'
import type { Channel, DispatchReceipt } from '../../types/contracts'
import { actionErrorText } from '../../lib/errors'
import { DownloadCap, Receipt } from './ReceiptList'
import { useRecipients } from './useDispatch'

const INPUT = 'mt-1 w-full rounded-control border border-line px-2 py-1 text-ink'

/** Channels, masked recipients (from api/.env only), PIN and dry run; then the receipt. */
export default function DispatchDialog(props: {
  advisoryId: string
  blockName: string
  resend: boolean
  onClose: (dispatched: boolean) => void
}) {
  const recipients = useRecipients()
  const [picked, setPicked] = useState<Record<Channel, boolean>>({ telegram: true, email: true })
  const [dryRun, setDryRun] = useState(true)
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [receipt, setReceipt] = useState<DispatchReceipt | null>(null)

  const r = recipients.status === 'ok' ? recipients.data : null
  const available: Record<Channel, boolean> = {
    telegram: r?.telegram.configured ?? false,
    email: r?.email.configured ?? false,
  }
  const channels = (['telegram', 'email'] as const).filter((c) => picked[c] && available[c])
  const valid = channels.length > 0 && (dryRun || pin.trim() !== '')

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      setReceipt(
        await dispatchAdvisory(props.advisoryId, {
          channels,
          dry_run: dryRun,
          resend: props.resend,
          pin: dryRun ? null : pin,
        }),
      )
    } catch (err) {
      setError(actionErrorText(err))
    } finally {
      setBusy(false)
    }
  }

  const title = `${props.resend ? 'Resend' : 'Dispatch'} advisory: ${props.blockName}`
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/30">
      <div
        role="dialog"
        aria-label={title}
        className="w-96 rounded-lg bg-white p-4 text-sm text-slate-800 shadow-xl"
      >
        <p className="mb-2 font-medium">{title}</p>
        <p className="rounded-control border border-line bg-surface px-2 py-1 text-xs text-ink-muted">
          Exercise: Cyclone Amphan 2020 replay. Messages are real (Telegram, e-mail) but marked as an
          exercise, and the CAP alert has status Exercise.
        </p>

        {receipt ? (
          <div className="mt-3 space-y-2">
            <Receipt receipt={receipt} />
            <DownloadCap advisoryId={props.advisoryId} />
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => props.onClose(!receipt.dry_run)}
                className="rounded-control bg-accent px-3 py-1 font-medium text-white hover:bg-accent-strong"
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          <form
            className="mt-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (valid) void submit()
            }}
          >
            {recipients.status === 'loading' && <p className="text-xs text-slate-500">Loading…</p>}
            {recipients.status === 'error' && (
              <p className="text-xs text-sev-cut">{recipients.message}</p>
            )}
            {r && (
              <fieldset className="space-y-1 text-xs">
                <legend className="mb-1 text-slate-600">Channels</legend>
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={picked.telegram && available.telegram}
                    disabled={!available.telegram}
                    onChange={(e) => setPicked({ ...picked, telegram: e.target.checked })}
                  />
                  <span>
                    Telegram{' '}
                    <span className="text-slate-500">
                      {r.telegram.configured ? `chat ${r.telegram.chat_id}` : '(not configured)'}
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    checked={picked.email && available.email}
                    disabled={!available.email}
                    onChange={(e) => setPicked({ ...picked, email: e.target.checked })}
                  />
                  <span>
                    E-mail{' '}
                    <span className="text-slate-500">
                      {r.email.configured ? r.email.to.join(', ') : '(not configured)'}
                    </span>
                  </span>
                </label>
                <p className="text-slate-400">Recipients are set in api/.env only.</p>
              </fieldset>
            )}

            <label className="mt-3 flex items-center gap-2 text-xs">
              <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
              Dry run (build and validate the CAP, send nothing)
            </label>
            {!dryRun && (
              <label className="mt-2 block text-xs text-slate-600">
                Dispatch PIN
                <input
                  className={INPUT}
                  type="password"
                  autoComplete="off"
                  value={pin}
                  onChange={(e) => setPin(e.target.value)}
                  autoFocus
                />
                {r && !r.pin_configured && (
                  <span className="text-sev-cut">DISPATCH_PIN is not set in api/.env.</span>
                )}
              </label>
            )}

            {error && <p className="mt-2 text-xs text-sev-cut">{error}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => props.onClose(false)}
                className="rounded px-3 py-1 text-slate-600 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!valid || busy}
                className="rounded-control bg-accent px-3 py-1 font-medium text-white hover:bg-accent-strong disabled:bg-slate-300"
              >
                {busy ? '…' : dryRun ? 'Dry run' : props.resend ? 'Resend' : 'Send'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
