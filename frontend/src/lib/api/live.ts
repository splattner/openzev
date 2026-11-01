import type { LiveCurve, LiveSnapshot } from '../../types/api'
import { api } from './client'

const BASE = '/metering/live/zevs/'

/** The ZEV's live figures right now, as far as the viewer may see them. Answers 404 while the feature is off or without access. */
export async function fetchLiveSnapshot(zevId: string): Promise<LiveSnapshot> {
  const { data } = await api.get<LiveSnapshot>(`${BASE}${zevId}/`)
  return data
}

/** The buckets of a civil day (`YYYY-MM-DD`, default today). */
export async function fetchLiveCurve(zevId: string, date?: string): Promise<LiveCurve> {
  const { data } = await api.get<LiveCurve>(`${BASE}${zevId}/curve/`, { params: date ? { date } : undefined })
  return data
}

function notFoundToNull<T>(request: Promise<T>): Promise<T | null> {
  return request.catch((error: unknown) => {
    if ((error as { response?: { status?: number } }).response?.status === 404) return null
    throw error
  })
}

/** `null` rather than an error when the feature is off or the caller may not see the ZEV (404). */
export function fetchLiveSnapshotOrNull(zevId: string): Promise<LiveSnapshot | null> {
  return notFoundToNull(fetchLiveSnapshot(zevId))
}

export function fetchLiveCurveOrNull(zevId: string, date?: string): Promise<LiveCurve | null> {
  return notFoundToNull(fetchLiveCurve(zevId, date))
}

/** Whether the live view is effective on this instance. Unlike the rest, this answers 200 while it is off. */
export async function fetchLiveEnabled(): Promise<boolean> {
  const { data } = await api.get<{ enabled: boolean }>('/metering/live/enabled/')
  return data.enabled
}
