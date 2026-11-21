import { expect, test } from '@playwright/test'
import { mockApi } from './page-anatomy-fixtures'
import type { DynamicTariffSource, TariffSeries, TariffVersion } from '../src/types/api'
import { de } from '../src/i18n/locales/de'
import { fr } from '../src/i18n/locales/fr'

test.use({ storageState: { cookies: [], origins: [] } })

const host = 'dynamic-tariffs.openzev.invalid'
const raw = `The host ${host} could not be resolved. Check the address for a typo.`
const source: DynamicTariffSource = {
  id: 'source', label: 'Dynamic grid source', url: `https://${host}/v2/tariffs`,
  api_version: 'v2_0_0', tariff_type: 'grid', tariff_name: 'demo-grid', enabled: false,
  last_fetch_status: 'failed', last_fetch_at: '2026-10-02T09:00:00Z', last_success_at: null,
  last_fetch_error: raw, last_fetch_diagnostics: [{
    code: 'host_unresolved', params: { host },
  }],
  covers_from: null, covers_to: null, point_count: 0, linked_tariff_count: 1, linked_zev_count: 1,
  supports_backfill: true, empty_on_not_found: false, aggregated_tariff_types: ['grid'],
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-10-02T09:00:00Z',
}
const version: TariffVersion = {
  id: 'dynamic', zev: '42', name: 'Dynamic grid', category: 'grid_fees', billing_mode: 'energy',
  energy_type: 'grid', valid_from: '2026-01-01', valid_to: null, fixed_price_chf: null,
  split_key: 'equal', notes: '', periods: [], dynamic_source: source.id,
}
const series: TariffSeries = {
  zev: '42', name: version.name, category: version.category, billing_mode: 'energy', energy_type: 'grid',
  version_count: 1, active_version_id: version.id, gaps: [], versions: [version],
}

// The code × language matrix is unit-tested; here: real rendering, legacy fallback,
// the technical-details disclosure and a language switch without a refetch.
const cases = [
  { legacy: false, expected: de.pages.tariffs.apiErrors.hostUnresolved.replace('{{host}}', host) },
  { legacy: true, expected: de.pages.dynamicSources.fetchFailed },
]

const language = 'de'
const diagnostic = source.last_fetch_diagnostics![0]

for (const { legacy, expected } of cases) {
  test(`stored fetch errors, legacy=${legacy}`, async ({ page }, testInfo) => {
    const errors = await mockApi(page)
    await page.route('**/api/v1/notifications/unread-count/', route => route.fulfill({ json: { count: 0 } }))
    await page.route('**/api/v1/metering/live/enabled/', route => route.fulfill({ json: { enabled: false } }))
    await page.addInitScript(lang => localStorage.setItem('openzev.language', lang), language)
    await page.route('**/api/v1/tariffs/tariffs/series/**', route => route.fulfill({ json: [series] }))
    await page.route('**/api/v1/tariffs/dynamic-sources/**', route => {
      if (new URL(route.request().url()).pathname.endsWith('/prices/')) return route.fulfill({ json: {
        source: source.id, date_from: '2026-09-03', date_to: '2026-10-02', points: [], gaps: [],
        stats: { point_count: 0, minimum_chf_per_kwh: null, maximum_chf_per_kwh: null,
          average_chf_per_kwh: null, negative_count: 0, gap_count: 0 },
      } })
      return route.fulfill({ json: [{ ...source, last_fetch_error: legacy ? raw : '', last_fetch_diagnostics: legacy ? [] : [diagnostic] }] })
    })
    await page.goto('/tariffs')
    await expect(page.locator('.issue-text[title]').first()).toHaveAttribute('title', expect.stringContaining(expected))
    await page.goto('/tariffs?tariff=42%3ADynamic+grid&version=dynamic')
    const summary = page.locator('.tariff-source-summary').first()
    for (const width of [1440, 400]) {
      await page.setViewportSize({ width, height: 900 })
      if (width === 400) await expect(page.locator('#app-sidebar')).not.toBeInViewport()
      await expect(summary.getByText(expected, { exact: true })).toBeVisible()
      await expect(page.locator('body')).not.toContainText(raw)
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`tariff-fetch-error-${width}.png`), fullPage: true })
    }
    await page.goto('/admin/dynamic-sources')
    for (const width of [1440, 400]) {
      await page.setViewportSize({ width, height: 900 })
      if (width === 400) await expect(page.locator('#app-sidebar')).not.toBeInViewport()
      await expect(page.getByText(expected, { exact: true })).toBeVisible()
      await expect(page.locator('body')).not.toContainText(raw)
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`admin-fetch-error-${width}.png`), fullPage: true })
    }
    if (legacy) {
      await page.locator('summary', { hasText: de.importDiagnostics.technicalDetails }).first().click()
      await expect(page.getByText(raw, { exact: true }).first()).toBeVisible()
    } else {
      await page.setViewportSize({ width: 1440, height: 900 })
      const fetchRequests: string[] = []
      page.on('request', request => {
        if (request.method() === 'POST') fetchRequests.push(request.url())
      })
      await page.locator('.user-menu-trigger').click()
      await page.locator('.language-selector').getByRole('button', { name: 'FR', exact: true }).click()
      await expect(page.getByText(fr.pages.tariffs.apiErrors.hostUnresolved.replace('{{host}}', host), { exact: true })).toBeVisible()
      expect(fetchRequests).toEqual([])
    }
    expect(errors).toEqual([])
  })
}
