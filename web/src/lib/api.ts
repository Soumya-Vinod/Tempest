// Typed client for the Tempest API. Route shapes: shared/contracts.md §5.
// Contract types come from ../types/contracts; do not redefine them here.
import type {
  ActionCountdown,
  CriticalLinks,
  Departures,
  CycloneTrack,
  InsuranceSummary,
  Advisory,
  AdvisoryApprove,
  AdvisoryCollection,
  AdvisoryCreate,
  AdvisoryNewDraft,
  AdvisoryReject,
  AdvisoryStatus,
  AdvisorySuggestions,
  AdvisoryUpdate,
  AuditLog,
  BlockId,
  DispatchReceipt,
  DispatchReceipts,
  DispatchRecipients,
  DispatchRequest,
  HazardLayerCollection,
  HazardType,
  Horizon,
  ImpactResultCollection,
  ImpactStatus,
  InfraFeatureCollection,
  InfraType,
  ReplayTimeline,
  RiskBreakdown,
  RiskScoreCollection,
  Timestep,
  TimestepParam,
  TriggerEventCollection,
  UnscoredAreaCollection,
} from '../types/contracts'

/** Empty in dev (Vite proxy); set VITE_API_BASE_URL for production builds. */
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

/** GET /health. Not part of the contract (contracts.md §5). */
export interface HealthResponse {
  status: 'ok'
  demo_mode: boolean
  configured: Record<string, boolean>
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `API request failed with ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

type Query = Record<string, string | undefined>

// --- Load control: at most MAX_IN_FLIGHT requests at a time, the rest wait in order. The free
// API instance has a fraction of a CPU; ~30 parallel requests on load made them all time out.

const MAX_IN_FLIGHT = 4
/** No response yet this long after the first request: the server is probably starting up. */
const WAKING_AFTER_MS = 3000

/** busy: a request is queued or in flight. waking: still no response WAKING_AFTER_MS in. */
export interface ApiStatus {
  busy: boolean
  waking: boolean
}

let pending = 0 // queued or in flight
let inFlight = 0
const waiting: (() => void)[] = []
let status: ApiStatus = { busy: false, waking: false }
let answered = false // any response (even an error) has arrived
let wakeTimer: number | undefined
const listeners = new Set<() => void>()

function setStatus(next: ApiStatus) {
  if (next.busy === status.busy && next.waking === status.waking) return
  status = next
  listeners.forEach((l) => l())
}

/** For useSyncExternalStore (lib/useApiStatus.ts). */
export const subscribeApiStatus = (listener: () => void) => {
  listeners.add(listener)
  return () => void listeners.delete(listener)
}
export const getApiStatus = () => status

async function queued<T>(run: () => Promise<T>): Promise<T> {
  pending++
  setStatus({ ...status, busy: true })
  if (!answered && wakeTimer === undefined) {
    wakeTimer = window.setTimeout(() => {
      if (!answered) setStatus({ ...status, waking: true })
    }, WAKING_AFTER_MS)
  }
  // A finishing request hands its slot straight to the next in line (inFlight unchanged).
  if (inFlight < MAX_IN_FLIGHT) inFlight++
  else await new Promise<void>((resolve) => waiting.push(resolve))
  try {
    return await run()
  } finally {
    pending--
    answered = true
    window.clearTimeout(wakeTimer)
    const next = waiting.shift()
    if (next) next()
    else inFlight--
    setStatus({ busy: pending > 0, waking: false })
  }
}

function request<T>(
  method: 'GET' | 'POST' | 'PATCH',
  path: string,
  options: { query?: Query; body?: unknown } = {},
): Promise<T> {
  return queued(() => send<T>(method, path, options))
}

/** One request, body read included (a slot is held until the whole response has arrived). */
async function send<T>(
  method: 'GET' | 'POST' | 'PATCH',
  path: string,
  { query, body }: { query?: Query; body?: unknown } = {},
): Promise<T> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) params.set(key, value)
  }
  const qs = params.size ? `?${params}` : ''
  const res = await fetch(`${BASE_URL}${path}${qs}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail ?? detail
    } catch {
      // Non-JSON error body; keep statusText.
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

const enc = encodeURIComponent

export const getHealth = () => request<HealthResponse>('GET', '/health')

// --- Dev A: hazard ---

export const getTimesteps = () => request<ReplayTimeline>('GET', '/api/hazard/timesteps')

export const getHazardLayer = (hazard_type: HazardType, timestep: TimestepParam) =>
  request<HazardLayerCollection>('GET', '/api/hazard/layers', { query: { hazard_type, timestep } })

/** Internal route (contracts.md §5, added in v1.1): the 25-point replay track. */
export const getHazardTrack = () => request<CycloneTrack>('GET', '/api/hazard/track')

// --- Dev B ---

export const getInfra = (infra_type?: InfraType) =>
  request<InfraFeatureCollection>('GET', '/api/exposure/infra', { query: { infra_type } })

export const getImpactResults = (
  timestep: TimestepParam,
  filters: { hazard_type?: HazardType; status?: ImpactStatus } = {},
  horizon: Horizon = 0, // v1.3 change, pending Dev A
) =>
  request<ImpactResultCollection>('GET', '/api/impact/results', {
    query: { timestep, ...filters, horizon: String(horizon) },
  })

/** v1.3 change, pending Dev A. Precomputed: expected and actual cut-offs, key moments. */
export const getCountdown = (timestep: TimestepParam) =>
  request<ActionCountdown>('GET', '/api/impact/countdown', { query: { timestep } })

/** v1.3 change, pending Dev A. Precomputed: last safe departure per cut-off facility. */
export const getDepartures = () => request<Departures>('GET', '/api/impact/departures')

/** v1.4 change, pending Dev A. Precomputed: the links the most departure routes use. */
export const getCriticalLinks = (timestep: TimestepParam, horizon: Horizon = 0) =>
  request<CriticalLinks>('GET', '/api/impact/critical-links', {
    query: { timestep, horizon: String(horizon) },
  })

export const getRiskScores = (timestep: TimestepParam, horizon: Horizon = 0) =>
  request<RiskScoreCollection>('GET', '/api/risk/scores', { query: { timestep, horizon: String(horizon) } })

/** added in v1.1. */
export const getRiskBreakdown = (timestep: TimestepParam, horizon: Horizon = 0) =>
  request<RiskBreakdown>('GET', '/api/risk/breakdown', { query: { timestep, horizon: String(horizon) } })

/** added in v1.1. Static: Kolkata and municipal areas outside the CD blocks. */
export const getUnscoredAreas = () =>
  request<UnscoredAreaCollection>('GET', '/api/risk/unscored-areas')

export const listAdvisories = (
  filters: { status?: AdvisoryStatus; block_id?: BlockId; timestep?: Timestep } = {},
) => request<AdvisoryCollection>('GET', '/api/advisory/', { query: filters })

/** added in v1.2. Blocks at or above the suggestion threshold. */
export const getAdvisorySuggestions = (timestep: TimestepParam) =>
  request<AdvisorySuggestions>('GET', '/api/advisory/suggestions', { query: { timestep } })

export const createAdvisory = (body: AdvisoryCreate) =>
  request<Advisory>('POST', '/api/advisory/', { body })

export const getAdvisory = (advisoryId: string) =>
  request<Advisory>('GET', `/api/advisory/${enc(advisoryId)}`)

export const updateAdvisory = (advisoryId: string, body: AdvisoryUpdate) =>
  request<Advisory>('PATCH', `/api/advisory/${enc(advisoryId)}`, { body })

export const approveAdvisory = (advisoryId: string, body: AdvisoryApprove) =>
  request<Advisory>('POST', `/api/advisory/${enc(advisoryId)}/approve`, { body })

/** added in v1.2. */
export const rejectAdvisory = (advisoryId: string, body: AdvisoryReject) =>
  request<Advisory>('POST', `/api/advisory/${enc(advisoryId)}/reject`, { body })

/** added in v1.2. Copies a finished advisory into a new draft. */
export const newDraftFrom = (advisoryId: string, body: AdvisoryNewDraft = {}) =>
  request<Advisory>('POST', `/api/advisory/${enc(advisoryId)}/new-draft`, { body })

/** added in v1.2. */
export const getAdvisoryAudit = (advisoryId: string) =>
  request<AuditLog>('GET', `/api/advisory/${enc(advisoryId)}/audit`)

/** added in v1.2: resend, dry_run and pin in the body. */
export const dispatchAdvisory = (advisoryId: string, body: DispatchRequest) =>
  request<DispatchReceipt>('POST', `/api/dispatch/${enc(advisoryId)}`, { body })

/** added in v1.2. Stored live receipts, oldest first. */
export const getDispatchReceipts = (advisoryId: string) =>
  request<DispatchReceipts>('GET', `/api/dispatch/${enc(advisoryId)}/receipts`)

/** added in v1.2. Configured recipients, masked. */
export const getDispatchRecipients = () =>
  request<DispatchRecipients>('GET', '/api/dispatch/recipients')

/** added in v1.2. Link target for "Download CAP". */
export const capXmlUrl = (advisoryId: string) =>
  `${BASE_URL}/api/dispatch/${enc(advisoryId)}/cap.xml`

export const getTriggers = (timestep: TimestepParam) =>
  request<TriggerEventCollection>('GET', '/api/insurance/triggers', { query: { timestep } })

/** added in v1.2: released totals per timestep and each block's first trigger. */
export const getInsuranceSummary = () =>
  request<InsuranceSummary>('GET', '/api/insurance/summary')
