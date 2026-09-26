import { capXmlUrl } from '../../lib/api'
import type { ChannelResult, DispatchReceipt } from '../../types/contracts'
import { useReceipts } from './useDispatch'

const CHANNEL_LABEL = { telegram: 'Telegram', email: 'E-mail' } as const
const STATUS_STYLE: Record<ChannelResult['status'], string> = {
  sent: 'bg-emerald-100 text-emerald-800',
  failed: 'bg-red-100 text-red-800',
  dry_run: 'bg-slate-100 text-slate-700',
}
const STATUS_LABEL: Record<ChannelResult['status'], string> = {
  sent: 'sent',
  failed: 'failed',
  dry_run: 'dry run: not sent',
}

const time = (iso: string) => iso.slice(0, 19).replace('T', ' ')

/** One dispatch: a line per channel with its status, provider id or error. */
export function Receipt({ receipt }: { receipt: DispatchReceipt }) {
  return (
    <div className="rounded border border-slate-200 p-2 text-xs">
      <p className="text-slate-500">
        {time(receipt.dispatched_at)} UTC
        {receipt.dry_run && ' · dry run'}
        {receipt.resend && ' · resend'}
      </p>
      <ul className="mt-1 space-y-1">
        {receipt.channels.map((c) => (
          <li key={c.channel} className="flex flex-wrap items-baseline gap-2">
            <span className="w-14 font-medium">{CHANNEL_LABEL[c.channel]}</span>
            <span className={`rounded px-1.5 py-0.5 ${STATUS_STYLE[c.status]}`}>
              {STATUS_LABEL[c.status]}
            </span>
            {c.provider_message_id && (
              <span className="truncate text-slate-400" title={c.provider_message_id}>
                id {c.provider_message_id}
              </span>
            )}
            {c.error && <span className="w-full text-red-700">{c.error}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function DownloadCap({ advisoryId }: { advisoryId: string }) {
  return (
    <a href={capXmlUrl(advisoryId)} download className="text-xs text-violet-700 underline">
      Download CAP
    </a>
  )
}

/** Stored receipts of an advisory's live dispatches, with the CAP link. */
export default function ReceiptList({
  advisoryId,
  version,
}: {
  advisoryId: string
  version: string
}) {
  const receipts = useReceipts(advisoryId, version)
  if (receipts.status === 'loading') return null
  if (receipts.status === 'error') {
    return <p className="mt-1 text-xs text-red-700">Receipts: {receipts.message}</p>
  }
  if (receipts.data.length === 0) return null
  return (
    <section>
      <div className="mt-4 flex items-baseline justify-between">
        <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
          Dispatch receipts
        </h3>
        <DownloadCap advisoryId={advisoryId} />
      </div>
      <div className="mt-1 space-y-2">
        {[...receipts.data].reverse().map((r) => (
          <Receipt key={r.dispatched_at} receipt={r} />
        ))}
      </div>
    </section>
  )
}
