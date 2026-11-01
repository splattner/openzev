import type { LiveCurve, LiveSnapshot, OwnSeries, ProductionForecast } from '../../types/api'
import { api } from './client'

const BASE = '/metering/live/zevs/'

/** The ZEV's live figures right now, as far as the viewer may see them. Answers 404 while the feature is off or without access. */
export async function fetchLiveSnapshot(zevId: string): Promise<LiveSnapshot> {
  const { data } = await api.get<LiveSnapshot>(`${BASE}${zevId}/`)
  return data
}

/** The buckets of a civil day (`YYYY-MM-DD`, default today); a manager, viewer or admin may name whose own values. */
export async function fetchLiveCurve(zevId: string, date?: string, participantId?: string): Promise<LiveCurve> {
  const params = { ...(date ? { date } : {}), ...(participantId ? { participant_id: participantId } : {}) }
  const { data } = await api.get<LiveCurve>(`${BASE}${zevId}/curve/`, { params })
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

export function fetchLiveCurveOrNull(zevId: string, date?: string, participantId?: string): Promise<LiveCurve | null> {
  return notFoundToNull(fetchLiveCurve(zevId, date, participantId))
}

export interface OwnSeriesParams {
  zevId: string
  dateFrom: string
  dateTo: string
  bucket: OwnSeries['bucket']
  /** Manager, viewer or admin: whose system. Omitted, it is the signed-in user's own. */
  participantId?: string
}

/** The own-system series of a civil range. Answers 404 while the energy data feature is off. */
export async function fetchOwnSeries({ zevId, dateFrom, dateTo, bucket, participantId }: OwnSeriesParams): Promise<OwnSeries> {
  const { data } = await api.get<OwnSeries>(`/metering/supplementary/zevs/${zevId}/own-series/`, {
    params: { date_from: dateFrom, date_to: dateTo, bucket, ...(participantId ? { participant_id: participantId } : {}) },
  })
  return data
}

/** Whether the live view is effective on this instance. Unlike the rest, this answers 200 while it is off. */
export async function fetchLiveEnabled(): Promise<boolean> {
  const { data } = await api.get<{ enabled: boolean }>('/metering/live/enabled/')
  return data.enabled
}

/** The ZEV's expected production hour by hour. `null` while the feature is off or the caller may not see the ZEV (404). */
export function fetchProductionForecastOrNull(zevId: string): Promise<ProductionForecast | null> {
  return notFoundToNull(api.get<ProductionForecast>(`${BASE}${zevId}/forecast/`).then((response) => response.data))
}
