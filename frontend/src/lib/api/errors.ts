import axios from 'axios'

function flattenErrorMessages(data: unknown, prefix = ''): string[] {
  if (data == null) {
    return []
  }

  if (typeof data === 'string') {
    return [prefix ? `${prefix}: ${data}` : data]
  }

  if (Array.isArray(data)) {
    return data.flatMap((entry) => flattenErrorMessages(entry, prefix))
  }

  if (typeof data === 'object') {
    const entries = Object.entries(data as Record<string, unknown>)
    return entries.flatMap(([key, value]) => {
      const nextPrefix = prefix ? `${prefix}.${key}` : key
      return flattenErrorMessages(value, nextPrefix)
    })
  }

  return [prefix ? `${prefix}: ${String(data)}` : String(data)]
}

export function formatApiError(error: unknown, fallbackMessage = 'Request failed.'): string {
  if (!axios.isAxiosError(error)) {
    return fallbackMessage
  }

  const responseData = error.response?.data
  if (!responseData) {
    return error.message || fallbackMessage
  }

  if (typeof responseData === 'string') {
    return responseData
  }

  if (typeof responseData === 'object' && responseData !== null) {
    const detail = (responseData as { detail?: unknown }).detail
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
  }

  const flattened = flattenErrorMessages(responseData)
  if (!flattened.length) {
    return fallbackMessage
  }

  const cleaned = flattened
    .map((entry) => entry.replace(/^non_field_errors\.?/i, 'Validation'))
    .map((entry) => entry.replace(/\./g, ' → '))

  return cleaned.join(' | ')
}

export function apiErrorPayload(error: unknown): Record<string, unknown> | null {
  if (!axios.isAxiosError(error)) {
    return null
  }
  const data = error.response?.data
  return typeof data === 'object' && data !== null
    ? data as Record<string, unknown>
    : null
}

export interface DynamicPriceGapPayload {
  code: 'dynamic_price_gap'
  tariff_name: string
  missing_at: string
}

export function dynamicPriceGapPayload(error: unknown): DynamicPriceGapPayload | null {
  const payload = apiErrorPayload(error)
  if (payload?.code !== 'dynamic_price_gap') return null
  if (typeof payload.tariff_name !== 'string' || typeof payload.missing_at !== 'string') return null
  return { code: 'dynamic_price_gap', tariff_name: payload.tariff_name, missing_at: payload.missing_at }
}
