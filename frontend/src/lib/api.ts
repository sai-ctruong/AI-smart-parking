export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || '/api/v1'
).replace(/\/$/, '')

export type Role = 'admin' | 'operator'
export type Status = 'empty' | 'occupied' | 'unknown'
export type AlertState = 'NONE' | 'FULL' | 'STALE'

export interface User {
  id: string
  username: string
  role: Role
  is_active: boolean
}

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
}

export interface Camera {
  id: string
  name: string
  is_active: boolean
  viewpoint_version: number
  reference_image: { sha256: string; width: number; height: number } | null
}

export interface Spot {
  id: string
  code: string
  is_active: boolean
  geometry_status: 'current' | 'needs_recalibration' | 'legacy_missing'
  polygon: { points: Array<{ x: number; y: number }> } | null
}

export interface Occupancy {
  snapshot_id: string | null
  camera_id: string
  captured_at: string | null
  as_of: string
  stale_after_seconds: number
  counts: {
    total: number
    empty: number
    occupied: number
    unknown: number
    available_confirmed: number
    occupancy_percent: number | null
  } | null
  alert_state: AlertState
}

export interface SnapshotSummary {
  snapshot_id: string
  camera_id: string
  captured_at: string
  uploaded_at: string
  total_spots: number
  empty_count: number
  occupied_count: number
  unknown_count: number
  occupancy_percent: number | null
  model_version: string | null
  reviewed_spots: number
  alert_state: AlertState
}

export interface SnapshotPage {
  items: SnapshotSummary[]
  page: number
  page_size: number
  total_items: number
}

export interface Prediction {
  prediction_id: string
  spot_id: string
  polygon_revision_id: string
  predicted_status: Status
  effective_status: Status
  review_version: number
  latest_review_id: string | null
  confidence: number | null
  model_version: string | null
  reason_code: string | null
  polygon: Array<{ x: number; y: number }>
}

export interface SnapshotDetail {
  snapshot_id: string
  camera_id: string
  timestamp: string
  total_spots: number
  empty_count: number
  occupied_count: number
  unknown_count: number
  occupancy_percent: number | null
  predictions: Prediction[]
  model_version: string | null
  processing_time_ms: number | null
  alert_state: AlertState
  image_url: string
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
  }
}

async function checkedResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const error = body?.error
    throw new ApiError(
      response.status,
      error?.code || 'REQUEST_FAILED',
      error?.message || 'Không thể hoàn tất yêu cầu.',
    )
  }
  return response.json() as Promise<T>
}

export async function loginRequest(
  username: string,
  password: string,
): Promise<LoginResponse> {
  return checkedResponse<LoginResponse>(
    await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
  )
}

export async function apiRequest<T>(
  path: string,
  token: string,
  onUnauthorized: () => void,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (response.status === 401) onUnauthorized()
  return checkedResponse<T>(response)
}

export async function apiBlob(
  path: string,
  token: string,
  onUnauthorized: () => void,
): Promise<Blob> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (response.status === 401) onUnauthorized()
  if (!response.ok)
    throw new ApiError(response.status, 'REQUEST_FAILED', 'Không thể tải tệp.')
  return response.blob()
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}
