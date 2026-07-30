import type {
  PaginatedResponse,
  Tariff,
  TariffInput,
  TariffPeriod,
  TariffPeriodInput,
  TariffPreset,
  TariffSeries,
  TariffVersionInput,
} from '../../types/api'
import { api } from './client'

export async function fetchTariffs(): Promise<PaginatedResponse<Tariff>> {
  const { data } = await api.get<PaginatedResponse<Tariff>>('/tariffs/tariffs/')
  return data
}

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

export async function fetchTariffPeriods(): Promise<PaginatedResponse<TariffPeriod>> {
  const { data } = await api.get<PaginatedResponse<TariffPeriod>>('/tariffs/periods/')
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

export async function exportTariffs(zevId: string): Promise<TariffPreset[]> {
  const { data } = await api.get<TariffPreset[]>('/tariffs/tariffs/export/', {
    params: { zev_id: zevId },
  })
  return data
}

export async function importTariffs(zevId: string, tariffs: TariffPreset[]): Promise<{ created: number; tariffs: Tariff[] }> {
  const { data } = await api.post<{ created: number; tariffs: Tariff[] }>('/tariffs/tariffs/import/', {
    zev_id: zevId,
    tariffs,
  })
  return data
}
