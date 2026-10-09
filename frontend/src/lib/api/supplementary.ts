import type {
  EligibleMeteringPoint,
  SupplementaryIngestResult,
  SupplementarySource,
  SupplementarySourceCreated,
  SupplementarySourceInput,
  SupplementarySourceUpdate,
} from '../../types/api'
import { api } from './client'
import { fetchAllPages } from './pagination'

const BASE = '/metering/supplementary/sources/'

/** Rows of a reconciliation the owner can open (the newest comparable days, per day). */
export interface SupplementaryReconciliationDetail {
  checked_at: string
  days_compared: number
  export_deviation_pct: number | null
  import_deviation_pct: number | null
  best_shift_intervals: number
  state: 'ok' | 'warn' | 'insufficient'
  days: Array<{
    date: string
    export_source_kwh: number
    export_meter_kwh: number
    import_source_kwh: number
    import_meter_kwh: number
  }>
}

export async function listSupplementarySources(): Promise<SupplementarySource[]> {
  return fetchAllPages<SupplementarySource>(BASE)
}

/** The flagged meters the user personally holds. Answers 404 while the feature is off. */
export async function listEligibleMeteringPoints(): Promise<EligibleMeteringPoint[]> {
  const { data } = await api.get<EligibleMeteringPoint[]>(`${BASE}eligible/`)
  return data
}

/** Whether the feature is on and the user holds a flagged meter; `false` rather than an error when it is off. */
export async function fetchEligibleOrNull(): Promise<EligibleMeteringPoint[] | null> {
  try {
    return await listEligibleMeteringPoints()
  } catch (error) {
    if ((error as { response?: { status?: number } }).response?.status === 404) return null
    throw error
  }
}

export async function createSupplementarySource(payload: SupplementarySourceInput): Promise<SupplementarySourceCreated> {
  const { data } = await api.post<SupplementarySourceCreated>(BASE, payload)
  return data
}

export async function updateSupplementarySource(id: string, payload: SupplementarySourceUpdate): Promise<SupplementarySource> {
  const { data } = await api.patch<SupplementarySource>(`${BASE}${id}/`, payload)
  return data
}

export async function deleteSupplementarySource(id: string): Promise<void> {
  await api.delete(`${BASE}${id}/`)
}

export async function disconnectSupplementarySource(id: string): Promise<SupplementarySource> {
  const { data } = await api.post<SupplementarySource>(`${BASE}${id}/disconnect/`)
  return data
}

export async function purgeSupplementaryReadings(
  id: string,
  range?: { dateFrom?: string; dateTo?: string },
): Promise<{ deleted: number }> {
  const { data } = await api.post<{ deleted: number }>(`${BASE}${id}/purge/`, {
    date_from: range?.dateFrom,
    date_to: range?.dateTo,
  })
  return data
}

export async function testSupplementarySource(id: string): Promise<{ ok: boolean }> {
  const { data } = await api.post<{ ok: boolean }>(`${BASE}${id}/test/`)
  return data
}

export async function syncSupplementarySource(id: string): Promise<{ queued: boolean }> {
  const { data } = await api.post<{ queued: boolean }>(`${BASE}${id}/sync/`)
  return data
}

export async function rotateSupplementaryPushToken(id: string): Promise<{ push_token: string; push_token_prefix: string }> {
  const { data } = await api.post<{ push_token: string; push_token_prefix: string }>(`${BASE}${id}/rotate-push-token/`)
  return data
}

export async function importSupplementaryCsv(
  id: string,
  file: File,
  options: { dryRun?: boolean } = {},
): Promise<SupplementaryIngestResult> {
  const body = new FormData()
  body.append('file', file)
  const { data } = await api.post<SupplementaryIngestResult>(`${BASE}${id}/import-csv/`, body, {
    params: options.dryRun ? { dry_run: 'true' } : undefined,
  })
  return data
}

export async function fetchSupplementaryReconciliation(id: string): Promise<SupplementaryReconciliationDetail> {
  const { data } = await api.get<SupplementaryReconciliationDetail>(`${BASE}${id}/reconciliation/`)
  return data
}
