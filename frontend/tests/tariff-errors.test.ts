import { beforeAll, describe, expect, it } from 'vitest'
import i18n from 'i18next'
import { de } from '../src/i18n/locales/de'
import { en } from '../src/i18n/locales/en'
import { fr } from '../src/i18n/locales/fr'
import { it as italian } from '../src/i18n/locales/it'
import contract from './fixtures/tariff-validation-errors.json'
import type { TariffValidationError } from '../src/types/api'
import { formatTariffError, formatTariffErrorData, splitTariffBandErrors, tariffErrorKeys } from '../src/features/tariffs/errors'

const translations = i18n.createInstance()
beforeAll(async () => {
  await translations.init({
    lng: 'de', fallbackLng: false,
    resources: { de: { translation: de }, en: { translation: en }, fr: { translation: fr }, it: { translation: italian } },
    interpolation: { escapeValue: false },
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
      ...coded('band_time_pair', field), path: ['initial_periods', index, field],
    })))
    const result = formatTariffError(codedResponse(entries), 'fallback', t)
    expect(result.split(t('pages.tariffs.apiErrors.bandTimePair'))).toHaveLength(3)
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
    } } }, 'fallback', t)).toBe(`${t('pages.tariffs.form.validFrom')}: This field is required.`)
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

it.each(['de', 'en', 'fr', 'it'])('translates indexed non-field diagnostics in %s', language => {
  const t = translations.getFixedT(language)
  for (const field of ['non_field_errors', '__all__']) {
    const band = { ...coded('bands_energy_only'), field: null, path: ['initial_periods', 0, field] }
    const { items, rest } = splitTariffBandErrors({ isAxiosError: true, response: { data: {
      initial_periods: [{ [field]: ['Reworded diagnostic'] }], validation_errors: [band],
    } } }, t)
    expect(items).toEqual([{ [field]: [t('pages.tariffs.apiErrors.bandsEnergyOnly')] }])
    expect(formatTariffErrorData(rest, 'bands rejected', t)).toBe('bands rejected')
  }
})

it.each(['de', 'en', 'fr', 'it'])('keeps unconsumed band diagnostics in the notice in %s', language => {
  const t = translations.getFixedT(language)
  const inline = { ...coded('band_time_pair', 'time_to'), path: ['initial_periods', 0, 'time_to'] }
  const extra = { ...coded('bands_energy_only'), path: ['initial_periods', 4, 'non_field_errors'] }
  const nested = { ...coded('max_length', 'label', { count: 2 }), path: ['initial_periods', 0, 'future', 'label'] }
  const range = coded('date_range', 'valid_to')
  const { items, rest } = splitTariffBandErrors({ isAxiosError: true, response: { data: {
    initial_periods: [{ time_to: ['Inline diagnostic'], label: ['Legacy label diagnostic'] }],
    valid_to: ['Range diagnostic'], validation_errors: [inline, extra, nested, range],
  } } }, t)
  expect(items).toEqual([{
    time_to: [t('pages.tariffs.apiErrors.bandTimePair')], label: ['Legacy label diagnostic'],
  }])
  expect(rest?.validation_errors).toEqual([extra, nested, range])
  const notice = formatTariffErrorData(rest, 'fallback', t)
  expect(notice).toContain(t('pages.tariffs.bandEntry.band', { number: 5 }))
  expect(notice).toContain(t('pages.tariffs.apiErrors.bandsEnergyOnly'))
  expect(notice).toContain(t('pages.tariffs.apiErrors.maxLength', { count: 2 }))
  expect(notice).toContain(t('pages.tariffs.apiErrors.dateRange'))
})

it.each(['de', 'en', 'fr', 'it'])('identifies the field behind a series identity conflict in %s', language => {
  const t = translations.getFixedT(language)
  expect(formatTariffError(codedResponse([coded('series_identity', 'category', { name: 'Grid' })]), 'fallback', t))
    .toBe(`${t('pages.tariffs.form.category')}: ${t('pages.tariffs.apiErrors.seriesIdentity', { name: 'Grid' })}`)
})

it.each(['de', 'en', 'fr', 'it'])('handles legacy root messages and wrapped responses in %s', language => {
  const t = translations.getFixedT(language)
  expect(formatTariffErrorData(['Readable root diagnostic.'], 'fallback', t)).toBe('Readable root diagnostic.')
  expect(formatTariffErrorData({ detail: ['Readable root diagnostic.'] }, 'fallback', t)).toBe('Readable root diagnostic.')
  expect(formatTariffErrorData({ detail: ['Readable root diagnostic.'], validation_errors: [coded('dynamic_bands')] }, 'fallback', t))
    .toBe(t('pages.tariffs.apiErrors.dynamicBands'))
})

it.each(['de', 'en', 'fr', 'it'])('uses the progression translation without rendering its response code in %s', language => {
  const t = translations.getFixedT(language)
  const response = { detail: 'Too many distinct bands.', code: 'too_many_bands', validation_errors: [coded('too_many_bands')] }
  expect(formatTariffErrorData(response, 'fallback', t)).toBe(t('pages.tariffs.progression.errors.tooManyBands'))
  expect(formatTariffErrorData({ ...response, validation_errors: null }, 'fallback', t)).toBe(response.detail)
})

it('explains the exact-URL configuration restriction', () => {
  const text = formatTariffError(codedResponse([coded('source_range')]), 'fallback', translations.getFixedT('en'))
  expect(text).toBe('Exact-URL sources cannot support date-range queries.')
})

it.each(['de', 'en', 'fr', 'it'])('localizes catch-all conflicts with month parameters in %s', language => {
  const t = translations.getFixedT(language)
  expect(formatTariffError(codedResponse([coded('catch_all_conflict', 'time_from', { months: [1, 3] })]), 'fallback', t))
    .toBe(t('pages.tariffs.apiErrors.catchAllConflict', { months: `${t('pages.tariffs.monthsShort.jan')}, ${t('pages.tariffs.monthsShort.mar')}` }))
})

it.each(['de', 'en', 'fr', 'it'])('uses context for empty lists in %s', language => {
  const t = translations.getFixedT(language)
  for (const [field, key] of [['initial_periods', 'emptyBands'], ['selections', 'emptySelections'], ['other', 'emptyList']]) {
    const error = { ...coded('empty'), path: [field, 'non_field_errors'] }
    expect(formatTariffError(codedResponse([error]), 'fallback', t)).toBe(t(`pages.tariffs.apiErrors.${key}`))
  }
  const legacy = { selections: { non_field_errors: ['This list may not be empty.'] } }
  expect(formatTariffErrorData(legacy, 'fallback', t)).toBe('This list may not be empty.')
})

it.each(['de', 'en', 'fr', 'it'])('translates supported source, history and import fields in %s', language => {
  const t = translations.getFixedT(language)
  for (const [field, key] of [
    ['url', 'pages.dynamicSources.form.url'], ['api_version', 'pages.dynamicSources.form.apiVersion'],
    ['tariff_type', 'pages.dynamicSources.form.tariffType'], ['tariff_name', 'pages.dynamicSources.form.tariffName'],
    ['dynamic_tariff_name', 'pages.dynamicSources.form.tariffName'],
    ['date_from', 'pages.dynamicSources.history.dateFrom'], ['date_to', 'pages.dynamicSources.history.dateTo'],
    ['zev', 'admin.fields.zev'], ['confirmation', 'pages.tariffs.apiErrorFields.confirmation'],
    ['document_digest', 'pages.tariffs.apiErrorFields.documentDigest'],
  ]) {
    expect(translations.exists(key, { lng: language }), key).toBe(true)
    const code = field.startsWith('date_') ? 'invalid_date' : 'required'
    const result = formatTariffError(codedResponse([coded(code, field)]), 'fallback', t)
    expect(result).toBe(`${t(key)}: ${t(code === 'invalid_date' ? 'pages.tariffs.apiErrors.invalidDate' : 'pages.tariffs.form.errorRequired')}`)
    expect(result).not.toContain(`${field}:`)
  }
})

it.each([
  ['source_in_use', {}], ['source_in_use', { tariff_count: '3', community_count: 2 }],
  ['max_length', {}], ['max_length', { count: '200' }], ['max_length', { count: -1 }],
  ['duplicate_date', { name: 'Grid', date: 'nonsense' }],
  ['duplicate_date', { name: 'Grid', date: '2026-02-30' }],
  ['duplicate_date', { date: '2026-01-01' }], ['http_status', { status: {} }],
  ['http_status', { status: 999 }], ['min_value', { value: {} }],
  ['document_size', { size: NaN }], ['host_unresolved', { host: [] }],
  ['flat_timed_conflict', { months: [99] }], ['catch_all_conflict', { months: [] }],
] as const)('keeps readable text for malformed %s parameters: %j', (code, params) => {
  for (const language of ['de', 'en', 'fr', 'it']) {
    expect(formatTariffError(codedResponse([coded(code, null, params)]), 'fallback', translations.getFixedT(language)))
      .toBe('Arbitrarily reworded server diagnostic.')
  }
})

it('passes only interpolation parameters to i18next', () => {
  const t = translations.getFixedT('en')
  const params = { count: 200, lng: 'de', defaultValue: 'wrong', interpolation: { prefix: 'wrong' } }
  expect(formatTariffError(codedResponse([coded('max_length', 'name', params)]), 'fallback', t))
    .toBe(`${t('pages.tariffs.form.name')}: ${t('pages.tariffs.apiErrors.maxLength', { count: 200 })}`)
})

it.each(['de', 'en', 'fr', 'it'])('localizes ordinary workflow failures in %s', language => {
  const t = translations.getFixedT(language)
  for (const [code, key, params] of [
    ['confirmation_mismatch', 'confirmationMismatch', { name: 'Source' }],
    ['source_in_use', 'sourceInUse', { tariff_count: 3, community_count: 2 }], ['source_protected', 'sourceProtected', {}], ['prices_in_use', 'pricesInUse', {}],
    ['fetch_unavailable', 'fetchUnavailable', {}], ['product_selection_required', 'productSelectionRequired', {}],
  ] as const) {
    expect(translations.exists(`pages.tariffs.apiErrors.${key}`, { lng: language })).toBe(true)
    expect(formatTariffError(codedResponse([coded(code, null, params)]), 'fallback', t))
      .toBe(t(`pages.tariffs.apiErrors.${key}`, params))
  }
})

it('retains readable uncoded diagnostics and ignores obsolete structured codes', () => {
  const t = translations.getFixedT('en')
  expect(formatTariffErrorData({ initial_periods: [{ time_to: ['Old readable sentence.'] }] }, 'fallback', t))
    .toBe(`Band 1: ${t('pages.tariffs.form.timeTo')}: Old readable sentence.`)
  expect(formatTariffError(codedResponse([coded('timed_band_required')]), 'fallback', t)).toBe('Arbitrarily reworded server diagnostic.')
  expect(formatTariffError(new Error('offline'), 'fallback', t)).toBe('fallback')
})

it.each(['constructor', 'toString', '__proto__'])('treats inherited object names as unknown metadata: %s', name => {
  const t = translations.getFixedT('en')
  expect(formatTariffError(codedResponse([coded(name)]), 'fallback', t)).toBe('Arbitrarily reworded server diagnostic.')
  expect(formatTariffError(codedResponse([coded('required', name)]), 'fallback', t))
    .toBe(`${name}: ${t('pages.tariffs.form.errorRequired')}`)
  expect(formatTariffError(codedResponse([coded('max_length', 'fixed_price_chf', { count: 2, billing_mode: name })]), 'fallback', t))
    .toBe(`${t('pages.tariffs.form.fixedPrice')}: ${t('pages.tariffs.apiErrors.maxLength', { count: 2 })}`)
})

it.each(['de', 'en', 'fr', 'it'])('preserves all diagnostics when band metadata is partly malformed in %s', language => {
  const t = translations.getFixedT(language)
  const band = { ...coded('invalid_number', 'price_chf_per_kwh'), path: ['initial_periods', 0, 'price_chf_per_kwh'] }
  const data = {
    initial_periods: [{ price_chf_per_kwh: ['Readable band error'] }],
    valid_to: ['Readable range error'], name: ['Readable name error'],
    validation_errors: [band, coded('date_range', 'valid_to'), { code: 'required' }],
  }
  const split = splitTariffBandErrors({ isAxiosError: true, response: { data } }, t)
  expect(split.items).toEqual([{ price_chf_per_kwh: ['Readable band error'] }])
  const notice = formatTariffErrorData(split.rest, 'fallback', t)
  expect(notice).toContain('Readable range error')
  expect(notice).toContain('Readable name error')
})

it.each(['de', 'en', 'fr', 'it'])('has every mapped error translation in %s', language => {
  for (const key of Object.values(tariffErrorKeys)) {
    expect(translations.exists(`pages.tariffs.apiErrors.${key}`, { lng: language }), key).toBe(true)
  }
})

it.each(['de', 'en', 'fr', 'it'])('keeps source dependency counts and distinguishes clearing prices in %s', language => {
  const t = translations.getFixedT(language)
  for (const counts of [{ tariff_count: 1, community_count: 1 }, { tariff_count: 7, community_count: 3 }]) {
    const text = formatTariffError(codedResponse([coded('source_in_use', null, counts)]), 'fallback', t)
    expect(text).toContain(String(counts.tariff_count))
    expect(text).toContain(String(counts.community_count))
    expect(text).not.toContain('{{')
  }
  const clear = formatTariffError(codedResponse([coded('prices_in_use')]), 'fallback', t)
  expect(clear).toBe(t('pages.tariffs.apiErrors.pricesInUse'))
  expect(clear).not.toBe(t('pages.tariffs.apiErrors.sourceProtected'))
})
