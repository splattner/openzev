import { isAxiosError } from 'axios'
import { dynamicFetchMessages, formatDynamicFetchError, formatTariffDiagnostic, formatTariffErrorData } from '../features/tariffs/errors'
import type { AppSettings, ApiDiagnostic } from '../types/api'
import type { Translate } from './translate'
import { formatShortDate } from './appSettings'
import { apiErrorPayload, formatApiError, formatApiErrorRest } from './api/errors'

export const importNoticeParameters: Record<string, string[]> = {
  price_rounded: ['value', 'rounded'], months_missing: ['count'],
  hours_missing: ['months'], bands_assigned: ['high', 'low', 'months'], name_shortened: [],
  demand_omitted: [], reactive_omitted: [], storage_omitted: [], storage_unreadable: [],
  components_included: ['tariff_type', 'components'],
  components_included_v2: ['tariff_type', 'components', 'extra_components'],
  components_included_exact: ['tariff_type', 'components', 'version'],
  series_demand_omitted: ['tariff_type', 'units'], series_reactive_omitted: ['tariff_type'],
  series_unit_missing: ['tariff_type'], series_fixed_omitted: ['tariff_type', 'units'],
  source_settings_kept: ['name'], source_disabled: ['name'], source_fetch_failed: ['name'],
  source_not_fetched: ['name'], percentage_bands_replaced: ['name'],
  charge_participant_omitted: ['name'], successor_omitted: [], sources_disconnected: ['count'],
  tariff_new: [], tariff_duplicate: ['date'],
  tariff_conflict: ['name', 'field', 'existing', 'requested'], tariff_mode_conflict: ['name', 'existing', 'requested'],
  tariff_new_version: ['name'],
  tariff_save_failed: [], archive_required: [], archive_invalid_zip: [],
  archive_corrupt: ['member'], archive_csv_invalid: ['member'], import_document: [],
}

/** Codes whose translation is generic guidance, so the English detail stays reachable. */
const BROAD_CODES = ['invalid_dynamic_response', 'import_document']
/** Dynamic-source names interpolated into notices; translated like the source form does. */
const SOURCE_TYPE_PARAMS = ['tariff_type', 'components', 'extra_components']

/** Whether the original English must stay behind “Technical details” beside the translation. */
export function keepsTechnicalDetails(value: unknown, t: Translate): boolean {
  if (value === null || typeof value !== 'object') return false
  const { code, params } = value as Partial<ApiDiagnostic>
  if (code === 'source_fetch_failed') return dynamicFetchMessages(params?.diagnostics, t).length === 0
  return BROAD_CODES.includes(String(code))
}

export function formatImportDiagnostic(value: unknown, t: Translate, settings?: AppSettings): string {
  if (value === null || typeof value !== 'object') return ''
  const { code, params } = value as Partial<ApiDiagnostic>
  if (typeof code !== 'string' || params === null || typeof params !== 'object' || Array.isArray(params)) return ''
  if (!Object.hasOwn(importNoticeParameters, code)) return formatTariffDiagnostic(value, t, settings)
  const options: Record<string, string | number> = {}
  for (const key of importNoticeParameters[code]) {
    const item = params[key]
    if (key === 'count') {
      if (typeof item !== 'number' || !Number.isSafeInteger(item) || item < 0) return ''
    } else if (typeof item !== 'string' || (!item.trim() && key !== 'months')) return ''
    options[key] = SOURCE_TYPE_PARAMS.includes(key)
      ? String(item).split(', ').map(type => t(`pages.dynamicSources.types.${type}`, { defaultValue: type })).join(', ')
      : item as string | number
  }
  if (code === 'source_fetch_failed') {
    options.error = formatDynamicFetchError({
      last_fetch_diagnostics: Array.isArray(params.diagnostics) ? params.diagnostics : [],
    }, t)
  }
  if (code === 'tariff_duplicate') options.date = formatShortDate(String(options.date), settings)
  if (code === 'tariff_conflict' || code === 'tariff_mode_conflict') {
    const fields: Record<string, string> = { category: 'category', billing_mode: 'billingMode', energy_type: 'energyType' }
    const field = code === 'tariff_mode_conflict' ? 'billing_mode' : String(options.field)
    if (code === 'tariff_conflict' && Object.hasOwn(fields, field)) options.field = t(`pages.tariffs.form.${fields[field]}`)
    const choices: Record<string, string> = { category: 'categories', billing_mode: 'billingModes', energy_type: 'energyTypes' }
    if (Object.hasOwn(choices, field)) {
      for (const key of ['existing', 'requested']) {
        options[key] = t(`pages.tariffs.${choices[field]}.${options[key]}`, { defaultValue: String(options[key]) })
      }
    }
  }
  const seasonal = ['hours_missing', 'bands_assigned'].includes(code) && options.months
  let text = t(`importDiagnostics.${code}${seasonal ? '_months' : ''}`, options)
  if (code === 'tariff_new_version') {
    if (typeof params.mode === 'string' && params.mode) {
      text += ` ${t('importDiagnostics.tariff_mode_matched', { mode: t(`pages.tariffs.billingModes.${params.mode}`, { defaultValue: params.mode }) })}`
    }
    for (const [field, key] of [['previous_end', 'tariff_previous_closed'], ['end', 'tariff_end_capped']] as const) {
      if (typeof params[field] === 'string' && params[field]) {
        text += ` ${t(`importDiagnostics.${key}`, { date: formatShortDate(params[field], settings) })}`
      }
    }
  }
  return text
}

export type ImportRequestFailure = { text: string; diagnostic?: unknown; message?: string }

/** Keep the safe English detail apart from the translated headline. */
export function importRequestFailure(error: unknown, t: Translate, settings?: AppSettings): ImportRequestFailure {
  const payload = apiErrorPayload(error)
  if (!payload) return { text: formatApiError(error, '') }
  const { validation_errors: fieldErrors, diagnostic } = payload
  const text = formatApiErrorRest(Object.fromEntries(Object.entries(payload)
    .filter(([key]) => !['validation_errors', 'diagnostic', 'code'].includes(key))), '')
  if (formatImportDiagnostic(diagnostic, t, settings)) return { text, diagnostic }
  // Field errors keep their field labels and every entry, as on other tariff forms.
  const message = Array.isArray(fieldErrors) ? formatTariffErrorData({ validation_errors: fieldErrors }, '', t, settings) : ''
  if (message) return { text, message }
  const status = isAxiosError(error) ? error.response?.status ?? 0 : 0
  return [401, 403].includes(status) ? { text, diagnostic: { code: 'permission_denied', params: {} } } : { text }
}
