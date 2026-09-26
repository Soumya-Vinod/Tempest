// Typed client for the Tempest API. Route shapes: shared/contracts.md §5.
// Contract types come from ../types/contracts; do not redefine them here.
import type {
  Advisory,
  AdvisoryApprove,
  AdvisoryCollection,
  AdvisoryCreate,
  AdvisoryStatus,
  AdvisoryUpdate,
  BlockId,
  DispatchReceipt,
  DispatchRequest,
  HazardLayerCollection,
  HazardType,
  ImpactResultCollection,
  ImpactStatus,
  InfraFeatureCollection,
  InfraType,
  ReplayTimeline,
  RiskBreakdown,
  RiskScoreCollection,
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

async function request<T>(
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

// --- Dev B ---

export const getInfra = (infra_type?: InfraType) =>
  request<InfraFeatureCollection>('GET', '/api/exposure/infra', { query: { infra_type } })

export const getImpactResults = (
  timestep: TimestepParam,
  filters: { hazard_type?: HazardType; status?: ImpactStatus } = {},
) =>
  request<ImpactResultCollection>('GET', '/api/impact/results', {
    query: { timestep, ...filters },
  })

export const getRiskScores = (timestep: TimestepParam) =>
  request<RiskScoreCollection>('GET', '/api/risk/scores', { query: { timestep } })

/** v1.1 change, pending Dev A. */
export const getRiskBreakdown = (timestep: TimestepParam) =>
  request<RiskBreakdown>('GET', '/api/risk/breakdown', { query: { timestep } })

/** v1.1 change, pending Dev A. Static: Kolkata and municipal areas outside the CD blocks. */
export const getUnscoredAreas = () =>
  request<UnscoredAreaCollection>('GET', '/api/risk/unscored-areas')

export const listAdvisories = (filters: { status?: AdvisoryStatus; block_id?: BlockId } = {}) =>
  request<AdvisoryCollection>('GET', '/api/advisory/', { query: filters })

export const createAdvisory = (body: AdvisoryCreate) =>
  request<Advisory>('POST', '/api/advisory/', { body })

export const getAdvisory = (advisoryId: string) =>
  request<Advisory>('GET', `/api/advisory/${enc(advisoryId)}`)

export const updateAdvisory = (advisoryId: string, body: AdvisoryUpdate) =>
  request<Advisory>('PATCH', `/api/advisory/${enc(advisoryId)}`, { body })

export const approveAdvisory = (advisoryId: string, body: AdvisoryApprove) =>
  request<Advisory>('POST', `/api/advisory/${enc(advisoryId)}/approve`, { body })

export const dispatchAdvisory = (advisoryId: string, body: DispatchRequest) =>
  request<DispatchReceipt>('POST', `/api/dispatch/${enc(advisoryId)}`, { body })

export const getTriggers = (timestep: TimestepParam) =>
  request<TriggerEventCollection>('GET', '/api/insurance/triggers', { query: { timestep } })
