import type { AttentionItem, ReadinessPeriod, ReadinessResponse } from '../../types/api'
import { api } from './client'

/**
 * Readiness / attention API (contract:
 * docs/specs/2026-03-invoice-lifecycle-and-communication.md §5.6a).
 *
 * Two stable URLs: the readiness cockpit (where am I in this period?) and
 * the attention list (what needs me across periods?). The backend resolves
 * the cockpit period server-side so the dashboard needs no date picker.
 */

export async function fetchReadiness(zevId: string): Promise<ReadinessResponse> {
    const { data } = await api.get<ReadinessResponse>('/invoices/invoices/readiness/', {
        params: { zev_id: zevId },
    })
    return data
}

export async function fetchReadinessList(zevId: string): Promise<ReadinessPeriod[]> {
  const { data } = await api.get<{ zev_id: string; periods: ReadinessPeriod[] }>(
    '/invoices/invoices/readiness/',
    { params: { zev_id: zevId, periods: 'all' } },
  )
  return data.periods
}

export async function fetchAttention(zevId: string): Promise<AttentionItem[]> {
  const { data } = await api.get<{ zev_id: string; items: AttentionItem[] }>(
    '/invoices/invoices/attention/',
    { params: { zev_id: zevId } },
  )
  return data.items
}
