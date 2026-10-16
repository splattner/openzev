import type { Charge, ChargeInput, ChargePreview } from '../../types/api'
import { api } from './client'
import { fetchAllPages } from './pagination'

const BASE = '/invoices/charges/'

/** The one-off charges of a community, newest first. */
export async function fetchCharges(zevId?: string): Promise<Charge[]> {
  return fetchAllPages<Charge>(BASE, zevId ? { zev_id: zevId } : undefined)
}

export async function createCharge(payload: ChargeInput): Promise<Charge> {
  const { data } = await api.post<Charge>(BASE, payload)
  return data
}

export async function updateCharge(id: string, payload: Partial<ChargeInput>): Promise<Charge> {
  const { data } = await api.patch<Charge>(`${BASE}${id}/`, payload)
  return data
}

export async function deleteCharge(id: string): Promise<void> {
  await api.delete(`${BASE}${id}/`)
}

/** Who would pay what for a charge as entered, exactly as the invoice engine will bill it. Saves nothing. */
export async function previewCharge(payload: ChargeInput): Promise<ChargePreview> {
  const { data } = await api.post<ChargePreview>(`${BASE}preview/`, payload)
  return data
}
