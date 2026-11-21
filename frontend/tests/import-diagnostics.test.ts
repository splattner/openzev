import { createElement, act } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import i18n from 'i18next'
import { I18nextProvider } from 'react-i18next'
import { afterEach, beforeAll, expect, it } from 'vitest'
import { en } from '../src/i18n/locales/en'
import { de } from '../src/i18n/locales/de'
import { fr } from '../src/i18n/locales/fr'
import { it as italian } from '../src/i18n/locales/it'
import { ImportDiagnostic } from '../src/components/ImportDiagnostic'
import { formatImportDiagnostic, importNoticeParameters, importRequestFailure } from '../src/lib/importDiagnostics'
import { renderWithProviders } from './helpers/render'

const translations = i18n.createInstance()
beforeAll(async () => {
  await translations.init({ lng: 'de', fallbackLng: false, resources: {
    en: { translation: en }, de: { translation: de }, fr: { translation: fr }, it: { translation: italian },
  }, interpolation: { escapeValue: false } })
})
const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach(cleanup => cleanup()))
const values: Record<string, string | number> = {
  value: '0.123456', rounded: '0.12346', count: 2, months: '1,2', high: '0.2', low: '0.1',
  tariff_type: 'grid', components: 'metering', extra_components: 'national_fees', version: 'v2.0.0',
  units: 'CHF/m', name: 'Demo', date: '2027-01-01', member: 'readings/meter.csv',
  field: 'billing_mode', existing: 'energy', requested: 'monthly_fee',
}

it.each(['en', 'de', 'fr', 'it'])('translates normal import notices in %s without backend catalogs', language => {
  const t = translations.getFixedT(language)
  for (const [code, required] of Object.entries(importNoticeParameters)) {
    const params = Object.fromEntries(required.map(key => [key, values[key]]))
    const text = formatImportDiagnostic({ code, params }, t)
    expect(text, code).not.toBe('')
    expect(text, code).not.toContain('importDiagnostics.')
    expect(text, code).not.toContain('pages.')
    expect(text, code).not.toContain('{{')
    expect(text, code).not.toContain('(s)')
  }
  const sourceFailure = formatImportDiagnostic({ code: 'source_fetch_failed', params: {
    name: 'Demo', diagnostics: [null, { code: 'http_status', params: { status: 502 } }],
  } }, t)
  expect(sourceFailure).toContain('502')
  expect(sourceFailure).not.toContain(t('pages.dynamicSources.fetchFailed'))
  for (const count of [1, 2]) {
    expect(formatImportDiagnostic({ code: 'sources_disconnected', params: { count } }, t))
      .toBe(t('importDiagnostics.sources_disconnected', { count }))
  }
})

it('keeps version dates and matched billing modes in the preview explanation', () => {
  const t = translations.getFixedT('de')
  const text = formatImportDiagnostic({ code: 'tariff_new_version', params: {
    name: 'Demo', mode: 'monthly_fee', previous_end: '2026-12-31', end: '2027-12-31',
  } }, t)
  expect(text).toContain('Demo')
  expect(text).toContain('31.12.2026')
  expect(text).toContain('31.12.2027')
  expect(text).toContain(t('pages.tariffs.billingModes.monthly_fee'))
})

it.each([null, {}, { code: 'future_code', params: {} }, { code: 'price_rounded', params: {} },
  { code: 'sources_disconnected', params: { count: true } }, { code: 'archive_corrupt', params: [] },
])('leaves unclassified or malformed diagnostic metadata to the localized fallback: %j', value => {
  expect(formatImportDiagnostic(value, translations.getFixedT('de'))).toBe('')
})

const fieldError = (code: string, field: string, params: Record<string, unknown> = {}) => ({
  code, field, path: ['selections', 0, field], params, message: 'English',
})

it('keeps safe legacy error text separate from codes and interpolation data', () => {
  const t = translations.getFixedT('de')
  const failure = importRequestFailure({ isAxiosError: true, response: { data: {
    detail: 'Unclassified parser detail', code: 'future', diagnostic: null,
    validation_errors: [fieldError('http_status', 'url', { status: 502 })],
  } } }, t)
  expect(failure.text).toBe('Unclassified parser detail')
  expect(failure.message).toContain('502')
})

it('keeps every field error and its field label, even beside an unknown top-level diagnostic', () => {
  const t = translations.getFixedT('de')
  const failure = importRequestFailure({ isAxiosError: true, response: { data: {
    diagnostic: { code: 'future_code', params: {} },
    validation_errors: [fieldError('required', 'billing_mode'), fieldError('required', 'name')],
  } } }, t)
  expect(failure.diagnostic).toBeUndefined()
  expect(failure.message).toContain(t('pages.tariffs.form.billingMode'))
  expect(failure.message).toContain(t('pages.tariffs.form.name'))
})

it('separates the selectable billing-mode conflict from rename-only conflicts', () => {
  const t = translations.getFixedT('en')
  const mode = formatImportDiagnostic({ code: 'tariff_mode_conflict', params: {
    name: 'Demo', existing: 'energy', requested: 'monthly_fee',
  } }, t)
  const field = formatImportDiagnostic({ code: 'tariff_conflict', params: {
    name: 'Demo', field: 'category', existing: 'grid_fees', requested: 'energy',
  } }, t)
  expect(mode).toContain(`Choose ${t('pages.tariffs.billingModes.energy')}`)
  expect(field).toContain('Rename')
  expect(field).not.toContain('Choose')
})

it('shows unknown English parser detail only after opening the translated disclosure', async () => {
  const raw = 'Unknown library parsing detail'
  const wrapped = createElement(I18nextProvider, { i18n: translations },
    createElement(ImportDiagnostic, { text: raw, fallback: 'Eintrag konnte nicht importiert werden.' }))
  const html = renderToStaticMarkup(wrapped)
  expect(html).toContain('Technische Details')
  expect(html).not.toContain(raw)
  const { container } = await renderWithProviders(wrapped, cleanups)
  await act(async () => { container.querySelector('summary')!.click() })
  expect(container.textContent).toContain(raw)
})

it.each([
  [[], true],
  [[{ code: 'http_status', params: { status: 502 } }], false],
])('keeps a reused source’s stored cause reachable when its diagnostics are %j', (diagnostics, disclosed) => {
  const raw = 'The reused dynamic price source is currently failing: upstream 503'
  const html = renderToStaticMarkup(createElement(I18nextProvider, { i18n: translations },
    createElement(ImportDiagnostic, {
      text: raw, fallback: 'Fallback',
      diagnostic: { code: 'source_fetch_failed', params: { name: 'Demo', diagnostics } },
    })))
  expect(html).toContain('Demo')
  expect(html.includes('Technische Details')).toBe(disclosed)
})

it('translates dynamic source types inside component notices', () => {
  const t = translations.getFixedT('de')
  const text = formatImportDiagnostic({ code: 'components_included', params: {
    tariff_type: 'grid', components: 'metering, national_fees',
  } }, t)
  expect(text).toContain(t('pages.dynamicSources.types.grid'))
  expect(text).toContain(`${t('pages.dynamicSources.types.metering')}, ${t('pages.dynamicSources.types.national_fees')}`)
})
