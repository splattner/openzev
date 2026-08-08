import type { AuditEvent, AuditEventFilters, AuditFilterOptions, PaginatedResponse } from '../../types/api'
import { api } from './client'

function sanitizeFilters(filters?: AuditEventFilters): Record<string, string | number> {
  if (!filters) {
    return {}
  }

  const entries = Object.entries(filters).filter(([, value]) => {
    if (value == null) {
      return false
    }
    if (typeof value === 'string') {
      return value.trim().length > 0
    }
    return true
  })

  return Object.fromEntries(entries) as Record<string, string | number>
}

export async function fetchAuditEvents(filters?: AuditEventFilters): Promise<PaginatedResponse<AuditEvent>> {
  const { data } = await api.get<PaginatedResponse<AuditEvent>>('/audit/events/', {
    params: sanitizeFilters(filters),
  })
  return data
}

export async function fetchAuditEvent(eventId: string): Promise<AuditEvent> {
  const { data } = await api.get<AuditEvent>(`/audit/events/${eventId}/`)
  return data
}

export async function fetchAuditFilterOptions(): Promise<AuditFilterOptions> {
  const { data } = await api.get<AuditFilterOptions>('/audit/events/filter-options/')
  return data
}
