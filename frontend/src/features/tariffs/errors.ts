import { isAxiosError } from 'axios'
import { formatApiError, splitIndexedErrors } from '../../lib/api/errors'
import { formatShortDate } from '../../lib/appSettings'
import type { AppSettings, TariffValidationError } from '../../types/api'
import { MONTH_KEYS } from './recurrence'
import { FIXED_PRICE_LABELS } from './labels'

type Translate = (key: string, options?: Record<string, unknown>) => string

export const tariffErrorKeys: Record<string, string> = {
  band_time_pair: 'bandTimePair',
  name_required: 'nameRequired',
  use_new_version: 'useNewVersion',
  date_range: 'dateRange',
  energy_type_required: 'energyTypeRequired',
  category: 'category',
  remove_bands_for_mode: 'removeBandsForMode',
  dynamic_bands: 'dynamicBands',
  minimum_dynamic: 'minimumDynamic',
  minimum_feed_in: 'minimumFeedIn',
  source_missing: 'sourceMissing',
  storage_refund: 'storageRefund',
  bands_energy_only: 'bandsEnergyOnly',
  months_blank: 'monthsBlank',
  price_required: 'priceRequired',
  percentage_mode_only: 'percentageModeOnly',
  percentage_required: 'percentageRequired',
  percentage_not_price: 'percentageNotPrice',
  remove_bands_for_source: 'removeBandsForSource',
  billed_source_change: 'billedSourceChange',
  billed_delete: 'billedDelete',
  initial_bands: 'initialBands',
  edit_existing_bands: 'editExistingBands',
  fixed_price_required: 'fixedPriceRequired',
  product_required: 'productRequired',
  source_identity: 'sourceIdentity',
  source_range: 'sourceRange',
  admin_source: 'adminSource',
  history_access: 'historyAccess',
  source_busy: 'sourceBusy',
  confirmation_mismatch: 'confirmationMismatch',
  source_in_use: 'sourceInUse',
  source_protected: 'sourceProtected',
  prices_in_use: 'pricesInUse',
  fetch_unavailable: 'fetchUnavailable',
  product_selection_required: 'productSelectionRequired',
  permission: 'permission',
  invalid_url: 'invalidUrl',
  import_url: 'importUrl',
  download_failed: 'downloadFailed',
  import_json: 'importJson',
  reference_missing: 'referenceMissing',
  duplicate_date: 'duplicateDate',
  name_exists: 'nameExists',
  overlap: 'overlap',
  series_identity: 'seriesIdentity',
  source_energy_only: 'sourceEnergyOnly',
  source_type_mismatch: 'sourceTypeMismatch',
  invalid_weekdays: 'weekdays',
  invalid_months: 'months',
  technology: 'technology',
  bfe_feed_in: 'bfeFeedIn',
  import_changed: 'importChanged',
  public_url: 'publicUrl',
  host_unresolved: 'hostUnresolved',
  http_status: 'httpStatus',
  document_size: 'documentSize',
  history_limit: 'historyLimit',
  invalid_date: 'invalidDate',
  invalid_time: 'invalidTime',
  invalid_choice: 'invalidChoice',
  does_not_exist: 'referenceMissing',
  not_found: 'referenceMissing',
  permission_denied: 'permission',
  min_value: 'minValue',
  max_value: 'maxValue',
  max_digits: 'maxDigits',
  max_decimal_places: 'maxDecimals',
  max_whole_digits: 'maxWholeDigits',
  max_length: 'maxLength',
  min_length: 'minLength',
}

const fieldKeys: Record<string, string> = {
  name: 'pages.tariffs.form.name', label: 'pages.dynamicSources.form.label',
  valid_from: 'pages.tariffs.form.validFrom', valid_to: 'pages.tariffs.form.validTo',
  category: 'pages.tariffs.form.category', billing_mode: 'pages.tariffs.form.billingMode',
  energy_type: 'pages.tariffs.form.energyType', dynamic_source: 'pages.tariffs.form.dynamicSource',
  minimum_price_chf_per_kwh: 'pages.tariffs.form.minimumPrice',
  price_chf_per_kwh: 'pages.tariffs.form.pricePerKwh', percentage: 'pages.tariffs.form.percentage',
  initial_percentage: 'pages.tariffs.form.initialPercentage', fixed_price_chf: 'pages.tariffs.form.fixedPrice',
  period_type: 'pages.tariffs.form.periodType', time_from: 'pages.tariffs.form.timeFrom',
  time_to: 'pages.tariffs.form.timeTo', weekdays: 'pages.tariffs.form.weekdays', months: 'pages.tariffs.form.months',
  url: 'pages.dynamicSources.form.url', api_version: 'pages.dynamicSources.form.apiVersion',
  tariff_type: 'pages.dynamicSources.form.tariffType', tariff_name: 'pages.dynamicSources.form.tariffName',
  dynamic_tariff_name: 'pages.dynamicSources.form.tariffName',
  date_from: 'pages.dynamicSources.history.dateFrom', date_to: 'pages.dynamicSources.history.dateTo',
  zev: 'admin.fields.zev', confirmation: 'pages.tariffs.apiErrorFields.confirmation',
  document_digest: 'pages.tariffs.apiErrorFields.documentDigest',
}

const parameterKeys: Record<string, string[]> = {
  duplicate_date: ['name', 'date'], name_exists: ['name'], overlap: ['name'], series_identity: ['name'],
  source_in_use: ['tariff_count', 'community_count'],
  confirmation_mismatch: ['name'], host_unresolved: ['host'], http_status: ['status'], document_size: ['size'],
  history_limit: ['count'], max_digits: ['count'], max_decimal_places: ['count'], max_whole_digits: ['count'],
  max_length: ['count'], min_length: ['count'], min_value: ['value'], max_value: ['value'],
}

function translationOptions(code: string, params: Record<string, unknown>, settings?: AppSettings) {
  const options: Record<string, unknown> = {}
  const requiredParams = Object.hasOwn(parameterKeys, code) ? parameterKeys[code] : []
  for (const key of requiredParams) {
    const value = params[key]
    if (['count', 'status', 'size', 'tariff_count', 'community_count'].includes(key)) {
      if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return null
      if (key !== 'size' && !Number.isInteger(value)) return null
      if (key === 'status' && (value < 100 || value > 599)) return null
    } else if (key === 'value') {
      if (!(typeof value === 'number' && Number.isFinite(value))
        && !(typeof value === 'string' && /^-?\d+(?:\.\d+)?$/.test(value))) return null
    } else {
      if (typeof value !== 'string' || !value.trim()) return null
      if (key === 'date') {
        const date = new Date(`${value}T00:00:00Z`)
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(date.getTime())
          || date.toISOString().slice(0, 10) !== value) return null
        options.date = formatShortDate(value, settings)
        continue
      }
    }
    options[key] = value
  }
  return options
}

function isCodedError(value: unknown): value is TariffValidationError {
  if (value === null || typeof value !== 'object') return false
  const entry = value as Partial<TariffValidationError>
  return typeof entry.code === 'string' && typeof entry.message === 'string'
    && (entry.field === null || typeof entry.field === 'string')
    && Array.isArray(entry.path) && entry.path.every(key => typeof key === 'string' || (Number.isInteger(key) && Number(key) >= 0))
    && entry.params !== null && typeof entry.params === 'object' && !Array.isArray(entry.params)
}

function formatCodedError(error: TariffValidationError, t: Translate, settings?: AppSettings): string {
  const { code, params, path, field, message } = error
  let text: string
  let withField = false
  const options = translationOptions(code, params, settings)
  if (['flat_timed_conflict', 'catch_all_conflict'].includes(code)) {
    const months = params.months
    const valid = Array.isArray(months) && months.length > 0
      && months.every(month => Number.isInteger(month) && month >= 1 && month <= 12)
    text = valid ? t(code === 'catch_all_conflict' ? 'pages.tariffs.apiErrors.catchAllConflict' : 'pages.tariffs.form.errorFlatTimed', {
      months: months.map(month => t(`pages.tariffs.monthsShort.${MONTH_KEYS[month - 1]}`)).join(', '),
    }) : message
  } else if (code === 'empty') {
    const key = path.includes('initial_periods') ? 'emptyBands' : path.includes('selections') ? 'emptySelections' : 'emptyList'
    text = t(`pages.tariffs.apiErrors.${key}`)
  } else if (['required', 'null', 'blank'].includes(code)) {
    text = t('pages.tariffs.form.errorRequired')
    withField = true
  } else if (code === 'invalid_number') {
    text = t('pages.tariffs.form.errorNumber')
    withField = true
  } else if (code === 'too_many_bands') {
    text = t('pages.tariffs.progression.errors.tooManyBands')
  } else if (Object.hasOwn(tariffErrorKeys, code) && options !== null) {
    text = t(`pages.tariffs.apiErrors.${tariffErrorKeys[code]}`, options)
    withField = ['invalid_date', 'invalid_time', 'invalid_choice', 'does_not_exist', 'min_value', 'max_value',
      'max_digits', 'max_decimal_places', 'max_whole_digits', 'max_length', 'min_length', 'fixed_price_required', 'series_identity'].includes(code)
  } else {
    text = message
    withField = true
  }
  if (withField && field) {
    const mode = typeof params.billing_mode === 'string' ? params.billing_mode : ''
    const feeLabel = field === 'fixed_price_chf' && Object.hasOwn(FIXED_PRICE_LABELS, mode)
      ? FIXED_PRICE_LABELS[mode as keyof typeof FIXED_PRICE_LABELS] : undefined
    const label = feeLabel ? t(feeLabel) : Object.hasOwn(fieldKeys, field) ? t(fieldKeys[field]) : field
    text = `${label}: ${text}`
  }
  const bandIndex = path.findIndex(key => key === 'initial_periods' || key === 'periods')
  const index = path[bandIndex + 1]
  return bandIndex >= 0 && typeof index === 'number'
    ? `${t('pages.tariffs.bandEntry.band', { number: index + 1 })}: ${text}` : text
}

function codedErrors(value: unknown): TariffValidationError[] | null {
  return Array.isArray(value) && value.every(isCodedError) ? value : null
}

export function formatTariffError(error: unknown, fallback: string, t: Translate, settings?: AppSettings): string {
  if (!isAxiosError(error) || error.response?.data == null) return formatApiError(error, fallback)
  return formatTariffErrorData(error.response.data, fallback, t, settings)
}

export function formatTariffErrorData(data: unknown, fallback: string, t: Translate, settings?: AppSettings): string {
  if (data !== null && typeof data === 'object' && 'validation_errors' in data) {
    const entries = codedErrors(data.validation_errors)
    if (entries?.length) {
      return [...new Set(entries.map(entry => formatCodedError(entry, t, settings)))].filter(Boolean).join(' ') || fallback
    }
  }
  const messages: string[] = []
  function collect(value: unknown, field = '', context = '') {
    if (Array.isArray(value)) {
      value.forEach((entry, index) => collect(entry, field,
        ['periods', 'initial_periods'].includes(field) && entry !== null && typeof entry === 'object'
          ? t('pages.tariffs.bandEntry.band', { number: index + 1 }) : context))
    } else if (value !== null && typeof value === 'object') {
      for (const [key, entry] of Object.entries(value)) {
        if (key === 'validation_errors' || (value === data && key === 'code')) continue
        collect(entry, ['detail', 'error', 'non_field_errors', '__all__'].includes(key) ? '' : key, context)
      }
    } else if (typeof value === 'string' && value.trim()) {
      const label = Object.hasOwn(fieldKeys, field) ? t(fieldKeys[field]) : field
      const text = label ? `${label}: ${value}` : value
      messages.push(context ? `${context}: ${text}` : text)
    }
  }
  collect(data)
  return [...new Set(messages)].join(' ') || fallback
}

export function splitTariffBandErrors(error: unknown, t: Translate, settings?: AppSettings) {
  const { items, rest } = splitIndexedErrors(error, 'initial_periods')
  if (!items) return { items, rest }
  // Initial creation renders inline rows; replacement versions use band-prefixed notices.
  const entries = codedErrors(rest?.validation_errors)
  if (!entries) return { items, rest }
  const bandEntries = entries.filter(entry => entry.path[0] === 'initial_periods')
  const consumedEntries = new Set<TariffValidationError>()
  const translatedItems = items.map((item, index) => {
    const fields = Object.entries(item).map(([field, messages]) => {
      const coded = bandEntries.filter(entry => entry.path.length === 3
        && entry.path[1] === index && entry.path[2] === field)
      coded.forEach(entry => consumedEntries.add(entry))
      const texts = coded.length
        ? coded.map(entry => formatCodedError({ ...entry, field: null, path: [] }, t, settings))
        : messages
      return [field, [...new Set(texts)]]
    })
    return Object.fromEntries(fields)
  })
  const remainingEntries = entries.filter(entry => !consumedEntries.has(entry))
  return { items: translatedItems, rest: rest ? { ...rest, validation_errors: remainingEntries } : null }
}
