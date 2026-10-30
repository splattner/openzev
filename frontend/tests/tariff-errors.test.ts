import { beforeAll, describe, expect, it } from 'vitest'
import i18n from 'i18next'
import { de } from '../src/i18n/locales/de'
import { en } from '../src/i18n/locales/en'
import { fr } from '../src/i18n/locales/fr'
import { it as italian } from '../src/i18n/locales/it'
import contract from './fixtures/tariff-validation-errors.json'
import type { TariffValidationError } from '../src/types/api'
import { formatTariffError, formatTariffErrorData, splitTariffBandErrors } from '../src/features/tariffs/errors'

const translations = i18n.createInstance()
beforeAll(async () => {
  await translations.init({
    lng: 'de', fallbackLng: false,
    resources: { de: { translation: de }, en: { translation: en }, fr: { translation: fr }, it: { translation: italian } },
    interpolation: { escapeValue: false },
  })
})

describe('tariff errors', () => {
  it('keeps localized month names in flat/timed conflicts', () => {
    const message = 'A flat band and a timed band cannot both apply in months 1,3: the flat price is used for every hour.'
    for (const language of ['de', 'en', 'fr', 'it']) {
      const t = translations.getFixedT(language)
      const result = formatTariffError({ isAxiosError: true, response: { data: { period_type: [message] } } }, 'fallback', t)
      expect(result).toContain(t('pages.tariffs.monthsShort.jan'))
      expect(result).toContain(t('pages.tariffs.monthsShort.mar'))
    }
  })

  it('uses configured dates and a translated fixed-fee field label', () => {
    const t = translations.getFixedT('en')
    const settings = { date_format_short: 'MM/dd/yyyy', date_format_long: 'd MMMM yyyy', date_time_format: 'dd.MM.yyyy HH:mm', updated_at: '' }
    const dateError = { isAxiosError: true, response: { data: { valid_from: ['A version of "Grid" already starts on 2026-10-25.'] } } }
    expect(formatTariffError(dateError, 'fallback', t, settings)).toContain('10/25/2026')
    const feeError = { isAxiosError: true, response: { data: { fixed_price_chf: ['Ensure that there are no more than 2 decimal places.'] } } }
    expect(formatTariffError(feeError, 'fallback', t)).toContain(t('pages.tariffs.form.fixedPrice'))
    expect(formatTariffError(feeError, 'fallback', t)).not.toContain('fixed_price_chf')
  })

  it.each([['de', 'bereits'], ['en', 'already starts'], ['fr', 'commence déjà'], ['it', 'inizia già']])('localizes a duplicate start date in %s', (language, phrase) => {
    const error = { isAxiosError: true, response: { data: { valid_from: ['A version of "test" already starts on 2026-10-25.'] } } }
    const result = formatTariffError(error, 'fallback', translations.getFixedT(language))
    expect(result).toContain(phrase)
    expect(result).toContain('test')
    expect(result).toContain('25.10.2026')
    expect(result).not.toContain('valid_from')
    expect(result).not.toContain('→')
  })

  it.each([
    ['valid_to must be on or after valid_from.', 'dateRange'],
    ['A tariff named "Existing" already exists in this ZEV.', 'nameExists'],
    ['A price band needs a price.', 'priceRequired'],
    ['A percentage band needs a percentage.', 'percentageRequired'],
    ['Remove this tariff\'s bands before changing its billing mode.', 'removeBandsForMode'],
    ['This tariff priced a non-cancelled invoice from its dynamic source. End its validity instead of deleting it.', 'billedDelete'],
    ['Create a replacement source instead of changing a price-series identity.', 'sourceIdentity'],
    ["The operator's server answered HTTP 404.", 'httpStatus'],
    ["The operator's document changed since the preview. Run the preview again and check what you are importing.", 'importChanged'],
  ])('localizes tariff validation: %s', (message, key) => {
    for (const language of ['de', 'en', 'fr', 'it']) {
      const t = translations.getFixedT(language)
      const result = formatTariffError({ isAxiosError: true, response: { data: { detail: message } } }, 'fallback', t)
      expect(result).toBe(t(`pages.tariffs.apiErrors.${key}`, { name: 'Existing', status: '404' }))
    }
  })

  it('keeps separate nested band errors, deduplicates matching endpoint errors and preserves decimal punctuation', () => {
    const t = translations.getFixedT('de')
    const result = formatTariffError({ isAxiosError: true, response: { data: { initial_periods: [
      { time_from: ['A timed band needs both a start and an end time.'], time_to: ['A timed band needs both a start and an end time.'] },
      { price_chf_per_kwh: ['Ensure this value is greater than or equal to 0.00001.'] },
    ] } } }, 'fallback', t)
    expect(result).toContain(t('pages.tariffs.bandEntry.band', { number: 1 }))
    expect(result).toContain(t('pages.tariffs.bandEntry.band', { number: 2 }))
    expect(result.split(t('pages.tariffs.form.errorTimedBand'))).toHaveLength(2)
    expect(result).toContain('0.00001')
    expect(result).not.toContain('price_chf_per_kwh')
    expect(result).not.toContain('→')
  })
  it.each(['time_from', 'time_to'])('translates a missing timed-band endpoint (%s)', field => {
    const error = { isAxiosError: true, response: { data: {
      [field]: ['A timed band needs both a start and an end time.'],
    } } }
    expect(formatTariffError(error, 'fallback', key => `translated:${key}`))
      .toBe('translated:pages.tariffs.form.errorTimedBand')
  })

  it.each(['1,2,3', '1,2,3,4,5,6,7,8,9,10,11,12'])('translates a flat/timed conflict for months %s', months => {
    const error = { isAxiosError: true, response: { data: {
      period_type: [`A flat band and a timed band cannot both apply in months ${months}: the flat price is used for every hour, so the timed bands would never apply. Give them different months, or make them all timed.`],
    } } }
    expect(formatTariffError(error, 'fallback', key => `translated:${key}`))
      .toBe('translated:pages.tariffs.form.errorFlatTimed')
  })

  it('preserves other server errors and the fallback for errors without a response', () => {
    expect(formatTariffError({ isAxiosError: true, response: { data: { period_type: ['Another conflict'] } } }, 'fallback', key => key))
      .toBe('pages.tariffs.form.periodType: Another conflict')
    expect(formatTariffError(new Error('offline'), 'fallback', key => key)).toBe('fallback')
  })
})


const codedResponse = (entries: TariffValidationError[], legacy = 'Old server text') => ({
  isAxiosError: true, response: { data: { detail: legacy, validation_errors: entries } },
})

const coded = (code: string, field: string | null = null, params: Record<string, unknown> = {}): TariffValidationError => ({
  code, field, path: field ? [field] : ['detail'], params, message: 'Arbitrarily reworded server diagnostic.',
})

describe('serialized tariff codes', () => {
  it.each(['de', 'en', 'fr', 'it'])('uses the backend contract independently of English wording in %s', language => {
    const t = translations.getFixedT(language)
    const errors: TariffValidationError[] = contract
    const expected = formatTariffError(codedResponse(errors), 'fallback', t)
    expect(formatTariffError(codedResponse(errors.map(entry => ({ ...entry, message: 'Completely new prose.' }))), 'fallback', t)).toBe(expected)
    expect(expected).toContain(t('pages.tariffs.monthsShort.jan'))
    expect(expected).toContain(t('pages.tariffs.monthsShort.mar'))
    expect(expected).toContain(t('pages.tariffs.bandEntry.band', { number: 2 }))
    expect(expected).toContain(t('pages.tariffs.form.errorRequired'))
    expect(expected).toContain(t('pages.tariffs.form.errorNumber'))
    expect(expected).not.toContain('server text')
    expect(expected).not.toContain('pages.tariffs.')
  })

  it.each(['de', 'en', 'fr', 'it'])('localizes standard and source/import codes in %s', language => {
    const t = translations.getFixedT(language)
    for (const [code, key, params] of [
      ['invalid_date', 'invalidDate', {}], ['invalid_time', 'invalidTime', {}],
      ['invalid_choice', 'invalidChoice', {}], ['does_not_exist', 'referenceMissing', {}],
      ['permission_denied', 'permission', {}], ['admin_source', 'adminSource', {}],
      ['product_required', 'productRequired', {}], ['source_identity', 'sourceIdentity', {}],
      ['http_status', 'httpStatus', { status: 404 }], ['history_limit', 'historyLimit', { count: 31 }],
      ['max_decimal_places', 'maxDecimals', { count: 5 }], ['min_value', 'minValue', { value: '0.00001' }],
      ['document_size', 'documentSize', { size: 5 }], ['host_unresolved', 'hostUnresolved', { host: 'example.test' }],
    ] as const) {
      expect(formatTariffError(codedResponse([coded(code, null, params)]), 'fallback', t))
        .toBe(t(`pages.tariffs.apiErrors.${key}`, params))
    }
  })

  it('formats dates using settings and fixed fees using their billing-mode label', () => {
    const t = translations.getFixedT('en')
    const settings = { date_format_short: 'MM/dd/yyyy', date_format_long: 'd MMMM yyyy', date_time_format: 'dd.MM.yyyy HH:mm', updated_at: '' }
    expect(formatTariffError(codedResponse([coded('duplicate_date', 'valid_from', { name: 'Grid', date: '2026-10-25' })]), 'fallback', t, settings)).toContain('10/25/2026')
    expect(formatTariffError(codedResponse([coded('max_decimal_places', 'fixed_price_chf', { count: 2, billing_mode: 'yearly_fee' })]), 'fallback', t))
      .toBe(`${t('pages.tariffs.form.yearlyFee')}: ${t('pages.tariffs.apiErrors.maxDecimals', { count: 2 })}`)
  })

  it('deduplicates timed endpoints within each band while retaining distinct band indexes', () => {
    const t = translations.getFixedT('en')
    const entries = [0, 1].flatMap(index => ['time_from', 'time_to'].map(field => ({
      ...coded('timed_band_required', field), path: ['initial_periods', index, field],
    })))
    const result = formatTariffError(codedResponse(entries), 'fallback', t)
    expect(result.split(t('pages.tariffs.form.errorTimedBand'))).toHaveLength(3)
    expect(result).toContain(t('pages.tariffs.bandEntry.band', { number: 1 }))
    expect(result).toContain(t('pages.tariffs.bandEntry.band', { number: 2 }))
  })

  it('preserves unknown diagnostics without displaying code or parameters', () => {
    const t = translations.getFixedT('en')
    const result = formatTariffError(codedResponse([coded('future_code', 'valid_from', { secret: 'Do not display' })]), 'fallback', t)
    expect(result).toBe(`${t('pages.tariffs.form.validFrom')}: Arbitrarily reworded server diagnostic.`)
    expect(result).not.toContain('future_code')
    expect(result).not.toContain('Do not display')
  })

  it.each([null, [], [{ code: 'required' }], 'broken'])('falls back to legacy fields for malformed/empty metadata: %j', metadata => {
    const t = translations.getFixedT('en')
    expect(formatTariffError({ isAxiosError: true, response: { data: {
      valid_from: ['This field is required.'], validation_errors: metadata,
    } } }, 'fallback', t)).toBe(`${t('pages.tariffs.form.validFrom')}: ${t('pages.tariffs.form.errorRequired')}`)
  })
})


it.each(['de', 'en', 'fr', 'it'])('localizes indexed errors and keeps the notice separate in %s', language => {
  const t = translations.getFixedT(language)
  const band = { ...coded('band_time_pair', 'time_to'), path: ['initial_periods', 1, 'time_to'] }
  const range = coded('date_range', 'valid_to')
  const result = splitTariffBandErrors({ isAxiosError: true, response: { data: {
    initial_periods: [{}, { time_to: ['New backend wording'] }],
    valid_to: ['New range wording'], validation_errors: [band, range],
  } } }, t)
  expect(result.items).toEqual([{}, { time_to: [t('pages.tariffs.apiErrors.bandTimePair')] }])
  expect(formatTariffErrorData(result.rest, 'fallback', t)).toBe(t('pages.tariffs.apiErrors.dateRange'))
  const onlyBands = splitTariffBandErrors({ isAxiosError: true, response: { data: {
    initial_periods: [{}, { time_to: ['New backend wording'] }], validation_errors: [band],
  } } }, t)
  expect(formatTariffErrorData(onlyBands.rest, 'bands rejected', t)).toBe('bands rejected')
})

it.each(['de', 'en', 'fr', 'it'])('localizes catch-all conflicts with month parameters in %s', language => {
  const t = translations.getFixedT(language)
  expect(formatTariffError(codedResponse([coded('catch_all_conflict', 'time_from', { months: [1, 3] })]), 'fallback', t))
    .toBe(t('pages.tariffs.apiErrors.catchAllConflict', { months: `${t('pages.tariffs.monthsShort.jan')}, ${t('pages.tariffs.monthsShort.mar')}` }))
})
