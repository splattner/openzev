import { isAxiosError } from 'axios'
import { formatApiError, splitIndexedErrors } from '../../lib/api/errors'
import { formatShortDate } from '../../lib/appSettings'
import type { AppSettings, TariffValidationError } from '../../types/api'
import { MONTH_KEYS } from './recurrence'
import { FIXED_PRICE_LABELS } from './useTariffForms'

type Translate = (key: string, options?: Record<string, unknown>) => string

// shortcut: keep this bounded mapping for older servers until the code contract is deployed everywhere.
const messageKeys: Record<string, string> = {
  'A name is required.': 'nameRequired',
  'Use new-version to add another version under the same name.': 'useNewVersion',
  'valid_to must be on or after valid_from.': 'dateRange',
  'date_to must be on or after date_from.': 'dateRange',
  'Energy-based tariffs require an energy type.': 'energyTypeRequired',
  'Energy tariffs require an energy type.': 'energyTypeRequired',
  'Percentage-of-energy tariffs require an energy type.': 'energyTypeRequired',
  'Choose energy, grid fees, levies or metering. One-off costs are charges, not tariffs.': 'category',
  "Remove this tariff's bands before changing its billing mode.": 'removeBandsForMode',
  'A tariff priced from a fetched series cannot carry price bands.': 'dynamicBands',
  'This tariff is priced from a fetched series; price bands do not apply.': 'dynamicBands',
  'A minimum price only applies to a tariff priced from a fetched series.': 'minimumDynamic',
  'A minimum price only applies to a feed-in tariff.': 'minimumFeedIn',
  'This price series no longer exists.': 'sourceMissing',
  'Storage refunds require storage-qualified metering and cannot be billed as exported energy.': 'storageRefund',
  'Tariff periods are only supported for energy-based tariffs.': 'bandsEnergyOnly',
  'Leave months blank to apply in every month.': 'monthsBlank',
  'A price band needs a price.': 'priceRequired',
  'Only percentage-of-energy tariffs take a percentage.': 'percentageModeOnly',
  'Only a percentage-of-energy tariff takes an initial percentage.': 'percentageModeOnly',
  'A percentage band needs a percentage.': 'percentageRequired',
  'A percentage band takes a percentage, not a price.': 'percentageNotPrice',
  "Remove this tariff's price bands before linking a fetched series.": 'removeBandsForSource',
  'This tariff priced a non-cancelled invoice from its current dynamic source. Create a new tariff version to change its price source.': 'billedSourceChange',
  'This tariff priced a non-cancelled invoice from its dynamic source. End its validity instead of deleting it.': 'billedDelete',
  'Initial bands are only supported when creating a static energy tariff.': 'initialBands',
  "Add bands from the tariff's own page to change an existing tariff.": 'editExistingBands',
  'Fixed-fee tariffs require a price.': 'fixedPriceRequired',
  "Version 2 price sources require a product name. Select or enter the operator's product name.": 'productRequired',
  'Source identity is immutable; create a replacement source.': 'sourceIdentity',
  'Create a replacement source instead of changing a price-series identity.': 'sourceIdentity',
  'An exact-URL source cannot support range queries.': 'sourceRange',
  'This endpoint does not accept a time range.': 'sourceRange',
  'Only administrators can operate shared price sources.': 'adminSource',
  'This price history is only available through a tariff in your ZEV.': 'historyAccess',
  'This source is currently being fetched. Try again shortly.': 'sourceBusy',
  'You do not have permission to perform this action.': 'permission',
  'You do not manage this ZEV.': 'permission',
  'The URL is invalid.': 'invalidUrl',
  'Enter a valid URL.': 'invalidUrl',
  'No URL was given.': 'importUrl',
  "The document could not be downloaded. Check the address, and that the operator's site is reachable.": 'downloadFailed',
  'The document at this URL is not valid JSON. Check that the link points at the machine-readable tariff file and not at a web page.': 'importJson',
  'This list may not be empty.': 'emptyBands',
  'Invalid pk - object does not exist.': 'referenceMissing',
  'Not found.': 'referenceMissing',
  'ZEV not found.': 'referenceMissing',
}

const codeKeys: Record<string, string> = {
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
  permission: 'permission',
  invalid_url: 'invalidUrl',
  import_url: 'importUrl',
  download_failed: 'downloadFailed',
  import_json: 'importJson',
  empty_bands: 'emptyBands',
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
  empty: 'emptyBands',
  min_value: 'minValue',
  max_value: 'maxValue',
  max_digits: 'maxDigits',
  max_decimal_places: 'maxDecimals',
  max_whole_digits: 'maxWholeDigits',
  max_length: 'maxLength',
  min_length: 'minLength',
}

const fieldKeys: Record<string, string> = {
  name: 'name', label: 'name', valid_from: 'validFrom', valid_to: 'validTo',
  category: 'category', billing_mode: 'billingMode', energy_type: 'energyType',
  dynamic_source: 'dynamicSource', minimum_price_chf_per_kwh: 'minimumPrice',
  price_chf_per_kwh: 'pricePerKwh', percentage: 'percentage', initial_percentage: 'initialPercentage',
  fixed_price_chf: 'fixedPrice',
  period_type: 'periodType', time_from: 'timeFrom', time_to: 'timeTo', weekdays: 'weekdays', months: 'months',
}

function translateMessage(message: string, field: string, t: Translate, settings?: AppSettings): string | null {
  const translated = (key: string, options?: Record<string, unknown>) => t(`pages.tariffs.apiErrors.${key}`, options)
  const fieldError = (text: string) => fieldKeys[field] ? `${t(`pages.tariffs.form.${fieldKeys[field]}`)}: ${text}` : text
  if (messageKeys[message]) return translated(messageKeys[message])
  if (message === 'A timed band needs both a start and an end time.') return t('pages.tariffs.form.errorTimedBand')
  const conflict = message.match(/^A flat band and a timed band cannot both apply in months ([\d,]+):/)
  if (conflict) return t('pages.tariffs.form.errorFlatTimed', {
    months: conflict[1].split(',').map(month => t(`pages.tariffs.monthsShort.${MONTH_KEYS[Number(month) - 1]}`)).join(', '),
  })

  let match = message.match(/^A version of "([\s\S]*)" already starts on (\d{4}-\d{2}-\d{2})\.$/)
  if (match) return translated('duplicateDate', { name: match[1], date: formatShortDate(match[2], settings) })
  match = message.match(/^A tariff named "([\s\S]*)" already exists in this ZEV\.$/)
  if (match) return translated('nameExists', { name: match[1] })
  match = message.match(/^Another tariff named "([\s\S]*)" in this ZEV already covers part of this validity period\./)
  if (match) return translated('overlap', { name: match[1] })
  match = message.match(/^Other versions of "([\s\S]*)" in this ZEV use /)
  if (match) return translated('seriesIdentity', { name: match[1] })
  if (message.startsWith('A price series bills per kWh, so it can only be used by a tariff billed by energy')) return translated('sourceEnergyOnly')
  if (message.startsWith('This price series serves ')) return translated('sourceTypeMismatch')
  if (message.startsWith('Weekdays must be comma-separated numbers between 0 and 6,')) return translated('weekdays')
  if (message.startsWith('Months must be comma-separated numbers between 1 and 12,')) return translated('months')
  if (message.startsWith('Select a technology: one of ')) return translated('technology')
  if (message.startsWith('The BFE reference market price prices exported energy;')) return translated('bfeFeedIn')
  if (message.startsWith("The operator's document changed since the preview.")) return translated('importChanged')
  if (message.startsWith('No tariff URL is set for this ZEV.')) return translated('importUrl')
  if (message.startsWith('Only http and https URLs can be imported, not ') || message.includes('does not resolve to a public address. Tariff documents must be fetched')) return translated('publicUrl')
  match = message.match(/^The host (.+) could not be resolved\. Check the address for a typo\.$/)
  if (match) return translated('hostUnresolved', { host: match[1] })
  match = message.match(/^The operator's server answered HTTP (\d+)\.$/)
  if (match) return translated('httpStatus', { status: match[1] })
  match = message.match(/^The document is (?:\d+ KB, )?larger than the (\d+) MB limit\.$/)
  if (match) return translated('documentSize', { size: match[1] })
  match = message.match(/^Price history is limited to (\d+) days\.$/)
  if (match) return translated('historyLimit', { count: Number(match[1]) })

  if (['This field is required.', 'This field may not be null.', 'This field may not be blank.', 'This value cannot be null.', 'This value cannot be blank.'].includes(message)) return fieldError(t('pages.tariffs.form.errorRequired'))
  if (['A valid number is required.', 'A valid integer is required.', 'Enter a number.', 'Enter a valid decimal.'].includes(message)) return fieldError(t('pages.tariffs.form.errorNumber'))
  if (message === 'Enter a valid date.' || message.startsWith('Date has wrong format.') || message.endsWith('is required as an ISO date (YYYY-MM-DD).')) return fieldError(translated('invalidDate'))
  if (message.startsWith('Time has wrong format.')) return fieldError(translated('invalidTime'))
  if (message.endsWith('is not a valid choice.')) return fieldError(translated('invalidChoice'))
  if (/^Invalid pk .+ - object does not exist\.$/.test(message)) return fieldError(translated('referenceMissing'))
  match = message.match(/^Ensure this value is (greater than or equal to|less than or equal to) (.+)\.$/)
  if (match) return fieldError(translated(match[1] === 'greater than or equal to' ? 'minValue' : 'maxValue', { value: match[2] }))
  const limits: [RegExp, string][] = [
    [/^Ensure that there are no more than (\d+) digits in total\.$/, 'maxDigits'],
    [/^Ensure that there are no more than (\d+) decimal places\.$/, 'maxDecimals'],
    [/^Ensure that there are no more than (\d+) digits before the decimal point\.$/, 'maxWholeDigits'],
    [/^Ensure (?:this field|this value) has (?:no more than|at most) (\d+) characters/, 'maxLength'],
    [/^Ensure (?:this field|this value) has (?:at least) (\d+) characters/, 'minLength'],
  ]
  for (const [pattern, key] of limits) {
    match = message.match(pattern)
    if (match) return fieldError(translated(key, { count: Number(match[1]) }))
  }
  return null
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
  if (code === 'timed_band_required') text = t('pages.tariffs.form.errorTimedBand')
  else if (['flat_timed_conflict', 'catch_all_conflict'].includes(code) && Array.isArray(params.months)) {
    text = t(code === 'catch_all_conflict' ? 'pages.tariffs.apiErrors.catchAllConflict' : 'pages.tariffs.form.errorFlatTimed', {
      months: params.months.filter((month): month is number => Number.isInteger(month) && month >= 1 && month <= 12)
        .map(month => t(`pages.tariffs.monthsShort.${MONTH_KEYS[month - 1]}`)).join(', '),
    })
  } else if (['required', 'null', 'blank'].includes(code)) {
    text = t('pages.tariffs.form.errorRequired')
    withField = true
  } else if (code === 'invalid_number') {
    text = t('pages.tariffs.form.errorNumber')
    withField = true
  } else if (Object.hasOwn(codeKeys, code)) {
    const options = { ...params }
    if (code === 'duplicate_date' && typeof params.date === 'string') options.date = formatShortDate(params.date, settings)
    text = t(`pages.tariffs.apiErrors.${codeKeys[code]}`, options)
    withField = ['invalid_date', 'invalid_time', 'invalid_choice', 'does_not_exist', 'min_value', 'max_value',
      'max_digits', 'max_decimal_places', 'max_whole_digits', 'max_length', 'min_length', 'fixed_price_required'].includes(code)
  } else {
    text = message
    withField = true
  }
  if (withField && field) {
    const mode = typeof params.billing_mode === 'string' ? params.billing_mode : ''
    const feeLabel = field === 'fixed_price_chf' ? FIXED_PRICE_LABELS[mode as keyof typeof FIXED_PRICE_LABELS] : undefined
    const label = feeLabel ? t(feeLabel) : fieldKeys[field] ? t(`pages.tariffs.form.${fieldKeys[field]}`) : field
    text = `${label}: ${text}`
  }
  const bandIndex = path.findIndex(key => key === 'initial_periods' || key === 'periods')
  const index = path[bandIndex + 1]
  return bandIndex >= 0 && typeof index === 'number'
    ? `${t('pages.tariffs.bandEntry.band', { number: index + 1 })}: ${text}` : text
}

export function formatTariffError(error: unknown, fallback: string, t: Translate, settings?: AppSettings): string {
  if (!isAxiosError(error) || error.response?.data == null) return formatApiError(error, fallback)
  return formatTariffErrorData(error.response.data, fallback, t, settings)
}

export function formatTariffErrorData(data: unknown, fallback: string, t: Translate, settings?: AppSettings): string {
  if (data !== null && typeof data === 'object' && 'validation_errors' in data) {
    const entries: unknown = data.validation_errors
    if (Array.isArray(entries) && entries.length && entries.every(isCodedError)) {
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
        if (key === 'validation_errors') continue
        collect(entry, ['detail', 'error', 'non_field_errors', '__all__'].includes(key) ? '' : key, context)
      }
    } else if (typeof value === 'string' && value.trim()) {
      const translated = translateMessage(value, field, t, settings)
      const label = fieldKeys[field] ? t(`pages.tariffs.form.${fieldKeys[field]}`) : field
      const text = translated ?? (label ? `${label}: ${value}` : value)
      messages.push(context ? `${context}: ${text}` : text)
    }
  }
  collect(data)
  return [...new Set(messages)].join(' ') || fallback
}


export function splitTariffBandErrors(error: unknown, t: Translate, settings?: AppSettings) {
  const { items, rest } = splitIndexedErrors(error, 'initial_periods')
  if (!items) return { items, rest }
  const entries = Array.isArray(rest?.validation_errors) ? rest.validation_errors.filter(isCodedError) : []
  const translated = items.map((item, index) => Object.fromEntries(Object.entries(item).map(([field, messages]) => {
    const coded = entries.filter(entry => entry.path[0] === 'initial_periods' && entry.path[1] === index && entry.field === field)
    const texts = coded.length ? coded.map(entry => formatCodedError({ ...entry, field: null, path: [] }, t, settings))
      : messages.map(message => translateMessage(message, '', t, settings) ?? message)
    return [field, [...new Set(texts)]]
  })))
  return { items: translated, rest: rest ? { ...rest, validation_errors: entries.filter(entry => entry.path[0] !== 'initial_periods') } : null }
}
