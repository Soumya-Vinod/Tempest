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

export type Query = Record<string, string | undefined>

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
    if (pending === 0) pumpLow()
  }
}

// --- Replay data: one shared promise per GET, and a low-priority lane (prefetch, sparkline) ---
//
// Replay GETs are memoized by request key, so the features' own caches and the prefetcher share
// one response. The low lane runs at most one request at a time, only while no foreground
// request is queued or in flight, and never sets `busy` (Play waits on the foreground only). A
// foreground request for a key still waiting in the low lane promotes it instead of fetching it
// twice. Queued prefetches can be dropped (cancelPrefetches) when the user changes direction.

// Only replay data is memoized: an explicit allowlist of exact GET paths (fixed for a given URL in
// a replay). Advisories, dispatch and health change as people act, so they are never memoized.
const MEMO_PATHS: ReadonlySet<string> = new Set([
  '/api/hazard/timesteps',
  '/api/hazard/track',
  '/api/hazard/layers',
  '/api/exposure/infra',
  '/api/impact/results',
  '/api/impact/countdown',
  '/api/impact/departures',
  '/api/impact/critical-links',
  '/api/risk/scores',
  '/api/risk/breakdown',
  '/api/risk/unscored-areas',
  '/api/insurance/triggers',
  '/api/insurance/summary',
])
const NEVER_MEMO_PREFIXES = ['/api/advisory', '/api/dispatch', '/health']
if (import.meta.env.DEV) {
  for (const path of MEMO_PATHS) {
    console.assert(
      !NEVER_MEMO_PREFIXES.some((p) => path.startsWith(p)),
      `api memo: ${path} must never be memoized`,
    )
  }
}
const MEMO_SIZE = 64
const memo = new Map<string, Promise<unknown>>()

interface LowEntry {
  key: string
  group: string
  run: () => Promise<void>
  reject: (err: unknown) => void
}
const lowQueue: LowEntry[] = []
let lowInFlight = 0

/** The request key: path plus the query parameters sorted by name (as the API's static cache). */
export function requestKey(path: string, query?: Query): string {
  const params = Object.entries(query ?? {})
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
  return params.length ? `${path}?${new URLSearchParams(params as [string, string][])}` : path
}

function pumpLow() {
  while (lowInFlight < 1 && pending === 0 && lowQueue.length) {
    const entry = lowQueue.shift()!
    lowInFlight++
    void entry.run().finally(() => {
      lowInFlight--
      pumpLow()
    })
  }
}

function remember(key: string, promise: Promise<unknown>) {
  memo.set(key, promise)
  promise.catch(() => {
    if (memo.get(key) === promise) memo.delete(key)
  })
  while (memo.size > MEMO_SIZE) memo.delete(memo.keys().next().value!)
}

/** Drop queued (not started) low-priority requests of `group` whose key `keep` rejects. */
export function cancelPrefetches(group: string, keep: (key: string) => boolean = () => false) {
  for (let i = lowQueue.length - 1; i >= 0; i--) {
    const e = lowQueue[i]
    if (e.group !== group || keep(e.key)) continue
    lowQueue.splice(i, 1)
    memo.delete(e.key)
    e.reject(new DOMException('Prefetch cancelled', 'AbortError'))
  }
}

interface RequestOptions {
  query?: Query
  body?: unknown
  /** Low-priority lane (GET replay data only), tagged with a group for cancelPrefetches. */
  low?: string
}

function request<T>(
  method: 'GET' | 'POST' | 'PATCH',
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const memoized = method === 'GET' && MEMO_PATHS.has(path)
  if (import.meta.env.DEV && memoized && NEVER_MEMO_PREFIXES.some((p) => path.startsWith(p))) {
    throw new Error(`api memo: ${path} must never be memoized`)
  }
  if (!memoized) return queued(() => send<T>(method, path, options))
  const key = requestKey(path, options.query)
  const hit = memo.get(key)
  if (hit) {
    memo.delete(key) // most recently used last
    memo.set(key, hit)
    if (!options.low) {
      // Still waiting in the low lane: run it in the foreground queue instead.
      const i = lowQueue.findIndex((e) => e.key === key)
      if (i >= 0) void queued(lowQueue.splice(i, 1)[0].run)
    }
    return hit as Promise<T>
  }
  let promise: Promise<T>
  if (options.low) {
    const group = options.low
    promise = new Promise<T>((resolve, reject) => {
      const run = () => send<T>(method, path, options).then(resolve, reject)
      lowQueue.push({ key, group, run, reject })
    })
    remember(key, promise)
    pumpLow()
  } else {
    promise = queued(() => send<T>(method, path, options))
    remember(key, promise)
  }
  return promise
}

/** A GET in the low lane, for warming the memo ahead of use (errors ignored). */
export function prefetch(group: string, path: string, query?: Query): void {
  request('GET', path, { query, low: group }).catch(() => {})
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
export const getCountdown = (timestep: TimestepParam, low?: string) =>
  request<ActionCountdown>('GET', '/api/impact/countdown', { query: { timestep }, low })

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
