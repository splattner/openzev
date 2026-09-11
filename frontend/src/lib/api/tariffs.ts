import type {
  DynamicPriceHistory,
  DynamicSourceFetchResult,
  DynamicTariffSource,
  DynamicTariffSourceInput,
  Tariff,
  TariffInput,
  TariffPeriod,
  TariffPeriodInput,
  TariffSeries,
  TariffVersionInput,
  VseTariffImportPreview,
  VseTariffImportResult,
  VseTariffImportSelection,
} from '../../types/api'
import { api } from './client'
import { fetchAllPages } from './pagination'

/**
 * Tariffs grouped into series (same name = versions of one tariff), each with
 * its active version and any gaps in its timeline already worked out by the
 * backend. Not paginated: the payload is one entry per tariff, not per version.
 */
export async function fetchTariffSeries(zevId?: string): Promise<TariffSeries[]> {
  const { data } = await api.get<TariffSeries[]>('/tariffs/tariffs/series/', {
    params: zevId ? { zev_id: zevId } : undefined,
  })
  return data
}

/** Add a version to the tariff's series, closing the previous one. */
export async function createTariffVersion(id: string, payload: TariffVersionInput): Promise<Tariff> {
  const { data } = await api.post<Tariff>(`/tariffs/tariffs/${id}/new-version/`, payload)
  return data
}

/** Copy a tariff under a new name, leaving the source's timeline untouched. */
export async function duplicateTariff(id: string, payload: TariffVersionInput & { name: string }): Promise<Tariff> {
  const { data } = await api.post<Tariff>(`/tariffs/tariffs/${id}/duplicate/`, payload)
  return data
}

/** Rename every version at once — the name is what groups them. */
export async function renameTariffSeries(id: string, name: string): Promise<Tariff> {
  const { data } = await api.post<Tariff>(`/tariffs/tariffs/${id}/rename-series/`, { name })
  return data
}

export async function createTariff(payload: TariffInput): Promise<Tariff> {
  const { data } = await api.post<Tariff>('/tariffs/tariffs/', payload)
  return data
}

export async function updateTariff(id: string, payload: Partial<TariffInput>): Promise<Tariff> {
  const { data } = await api.patch<Tariff>(`/tariffs/tariffs/${id}/`, payload)
  return data
}

export async function deleteTariff(id: string): Promise<void> {
  await api.delete(`/tariffs/tariffs/${id}/`)
}

export async function createTariffPeriod(payload: TariffPeriodInput): Promise<TariffPeriod> {
  const { data } = await api.post<TariffPeriod>('/tariffs/periods/', payload)
  return data
}

export async function updateTariffPeriod(id: string, payload: Partial<TariffPeriodInput>): Promise<TariffPeriod> {
  const { data } = await api.patch<TariffPeriod>(`/tariffs/periods/${id}/`, payload)
  return data
}

export async function deleteTariffPeriod(id: string): Promise<void> {
  await api.delete(`/tariffs/periods/${id}/`)
}

/**
 * Every configured dynamic price source — global, not scoped to a ZEV, so
 * this is what a tariff form's "use a dynamic source" picker reads from.
 */
export async function fetchDynamicTariffSources(): Promise<DynamicTariffSource[]> {
  return fetchAllPages<DynamicTariffSource>('/tariffs/dynamic-sources/')
}

export async function createDynamicTariffSource(payload: DynamicTariffSourceInput): Promise<DynamicTariffSource> {
  const { data } = await api.post<DynamicTariffSource>('/tariffs/dynamic-sources/', payload)
  return data
}

export async function updateDynamicTariffSource(
  id: string,
  payload: Partial<DynamicTariffSourceInput>,
): Promise<DynamicTariffSource> {
  const { data } = await api.patch<DynamicTariffSource>(`/tariffs/dynamic-sources/${id}/`, payload)
  return data
}

export async function fetchDynamicPriceHistory(
  id: string,
  dateFrom?: string,
  dateTo?: string,
): Promise<DynamicPriceHistory> {
  const { data } = await api.get<DynamicPriceHistory>(`/tariffs/dynamic-sources/${id}/prices/`, {
    params: { date_from: dateFrom, date_to: dateTo },
  })
  return data
}

export async function queueDynamicSourceFetch(id: string, backfill = false): Promise<DynamicSourceFetchResult> {
  const { data } = await api.post<DynamicSourceFetchResult>(`/tariffs/dynamic-sources/${id}/fetch/`, { backfill })
  return data
}

export async function clearDynamicSourcePrices(
  id: string,
  confirmation: string,
  reason: string,
): Promise<{ deleted_points: number }> {
  const { data } = await api.delete<{ deleted_points: number }>(`/tariffs/dynamic-sources/${id}/prices/`, {
    data: { confirmation, reason },
  })
  return data
}

/**
 * Read the grid operator's published tariff document and report what importing
 * it would do — nothing is written. Omitting `url` uses the address stored on
 * the ZEV.
 */
export async function previewVseTariffImport(payload: {
  zev: string
  url?: string
}): Promise<VseTariffImportPreview> {
  const { data } = await api.post<VseTariffImportPreview>('/tariffs/imports/vse/preview/', payload)
  return data
}

/**
 * Create the selected candidates. Only the keys and the billing mode chosen
 * for each travel back, never the tariff data: the server re-fetches the
 * document and refuses the write if `document_digest` no longer matches what
 * the preview showed.
 */
export async function applyVseTariffImport(payload: {
  zev: string
  url?: string
  selections: VseTariffImportSelection[]
  document_digest: string
  remember_url?: boolean
}): Promise<VseTariffImportResult> {
  const { data } = await api.post<VseTariffImportResult>('/tariffs/imports/vse/apply/', payload)
  return data
}
