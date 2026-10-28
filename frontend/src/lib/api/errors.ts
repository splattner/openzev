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

  return formatResponseData(responseData, fallbackMessage)
}

function formatResponseData(responseData: unknown, fallbackMessage: string): string {
  if (typeof responseData === 'string') {
    return responseData
  }

  if (typeof responseData === 'object' && responseData !== null) {
    const detail = (responseData as { detail?: unknown }).detail
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    const message = (responseData as { error?: unknown }).error
    if (typeof message === 'string' && message.trim()) {
      return message
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

/** Errors of one nested object, by field: `{ price_chf_per_kwh: ['A price band needs a price.'] }`. */
export type ItemFieldErrors = Record<string, string[]>

/**
 * A 400 on a nested list (`{ key: [{}, { field: ['...'] }] }`) split into the
 * errors of each item, by position in the request, and what is left of the
 * response once that key is taken out. `items` is `null` when the response
 * holds no such list (a plain message under the key is part of `rest`).
 */
export function splitIndexedErrors(
  error: unknown,
  key: string,
): { items: ItemFieldErrors[] | null; rest: Record<string, unknown> | null } {
  const payload = apiErrorPayload(error)
  if (!payload) return { items: null, rest: null }
  const { [key]: indexed, ...rest } = payload
  const isList = Array.isArray(indexed) && indexed.every((entry) => typeof entry === 'object' && entry !== null && !Array.isArray(entry))
  if (!isList) return { items: null, rest: payload }
  const items = (indexed as Array<Record<string, unknown>>).map((entry) => Object.fromEntries(
    Object.entries(entry).map(([field, messages]) => [field, (Array.isArray(messages) ? messages : [messages]).map(String)]),
  ))
  return { items, rest }
}

/** `formatApiError` for a response with one key taken out; `fallbackMessage` when nothing else is left. */
export function formatApiErrorRest(rest: Record<string, unknown> | null, fallbackMessage: string): string {
  return rest && Object.keys(rest).length > 0 ? formatResponseData(rest, fallbackMessage) : fallbackMessage
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
