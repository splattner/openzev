import { expect, test } from '@playwright/test'
import { mockApi } from './page-anatomy-fixtures'
import { de } from '../src/i18n/locales/de'
import { fr } from '../src/i18n/locales/fr'

test.use({ storageState: { cookies: [], origins: [] } })

for (const [language, locale] of [['de', de], ['fr', fr]] as const) {
  test(`archive notices use frontend ${language} translations`, async ({ page }, testInfo) => {
    const errors = await mockApi(page, { language })
    await page.route('**/api/v1/notifications/unread-count/', route => route.fulfill({ json: { count: 0 } }))
    await page.route('**/api/v1/metering/live/enabled/', route => route.fulfill({ json: { enabled: false } }))
    await page.route('**/api/v1/zev/zevs/transfer-sections/', route => route.fulfill({ json: { sections: [] } }))
    await page.route('**/api/v1/zev/zevs/inspect-archive/', route => route.fulfill({ status: 400, json: {
      detail: 'The uploaded file is not a valid ZIP archive.',
      diagnostic: { code: 'archive_invalid_zip', params: {} },
    } }))
    await page.goto('/admin/zevs')
    await page.getByRole('button', { name: locale.zevTransfer.importAction, exact: true }).click()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'invalid.zip', mimeType: 'application/zip', buffer: Buffer.from('invalid'),
    })
    for (const width of [1440, 400]) {
      await page.setViewportSize({ width, height: 900 })
      await expect(page.locator('.error-banner')).toHaveText(locale.importDiagnostics.archive_invalid_zip)
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      if (language === 'de') await page.screenshot({ path: testInfo.outputPath(`import-error-${width}.png`), fullPage: true })
    }
    expect(errors.filter(error => error !== 'Failed to load resource: the server responded with a status of 400 (Bad Request)')).toEqual([])
  })
}

test('unclassified archive details remain behind a translated disclosure', async ({ page }) => {
  await mockApi(page, { language: 'de' })
  await page.route('**/api/v1/notifications/unread-count/', route => route.fulfill({ json: { count: 0 } }))
  await page.route('**/api/v1/metering/live/enabled/', route => route.fulfill({ json: { enabled: false } }))
  await page.route('**/api/v1/zev/zevs/transfer-sections/', route => route.fulfill({ json: { sections: [] } }))
  const detail = 'Unknown archive schema field in manifest.json'
  await page.route('**/api/v1/zev/zevs/inspect-archive/', route => route.fulfill({ status: 400, json: { detail } }))
  await page.goto('/admin/zevs')
  await page.getByRole('button', { name: de.zevTransfer.importAction, exact: true }).click()
  await page.locator('input[type="file"]').setInputFiles({ name: 'legacy.zip', mimeType: 'application/zip', buffer: Buffer.from('legacy') })
  const notice = page.locator('.error-banner')
  await expect(notice).toContainText(de.zevTransfer.unreadableArchive)
  await expect(notice).not.toContainText(detail)
  await notice.getByText(de.importDiagnostics.technicalDetails, { exact: true }).click()
  await expect(notice).toContainText(detail)
  await page.setViewportSize({ width: 400, height: 900 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

for (const [language, locale] of [['de', de], ['fr', fr]] as const) {
  test(`VSE preview keeps billing warnings in ${language}`, async ({ page }, testInfo) => {
    const errors = await mockApi(page, { language })
    await page.route('**/api/v1/notifications/unread-count/', route => route.fulfill({ json: { count: 0 } }))
    await page.route('**/api/v1/metering/live/enabled/', route => route.fulfill({ json: { enabled: false } }))
    await page.route('**/api/v1/tariffs/imports/vse/preview/', route => route.fulfill({ json: {
      dso_name: 'Operator', dso_number: 1, source_url: 'https://operator.example/tariffs.json', document_digest: 'digest',
      errors: [], candidates: [{
        key: 'demo', name: 'Published tariff', category: 'grid_fees', billing_mode: 'energy', billing_mode_options: [],
        energy_type: 'grid', fixed_price_chf: null, valid_from: '2027-01-01', valid_to: '2027-12-31', notes: '',
        periods: [{ period_type: 'flat', price_chf_per_kwh: '0.1', time_from: null, time_to: null, weekdays: '', months: '' }],
        source_tariff_name: 'Published tariff', source_tariff_type: 'grid', source_customer_type: '', source_voltage_level: null,
        standard_basegroup: true, dynamic_url: '', series_name: 'Published tariff', status: 'new',
        detail: 'Creates a new tariff.', detail_diagnostic: { code: 'tariff_new', params: {} },
        warnings: ['Technical English: omitted demand charge'], warning_diagnostics: [{ code: 'demand_omitted', params: {} }],
        recommended: true, effective_valid_to: '2027-12-31',
      }],
    } }))
    await page.goto('/tariffs')
    await page.getByRole('button', { name: locale.pages.tariffs.import.action, exact: true }).click()
    await page.locator('input[type="url"]').fill('https://operator.example/tariffs.json')
    await page.getByRole('button', { name: locale.pages.tariffs.import.load, exact: true }).click()
    const modal = page.getByRole('dialog')
    for (const width of [1440, 400]) {
      await page.setViewportSize({ width, height: 900 })
      await expect(modal).toContainText(locale.importDiagnostics.demand_omitted)
      await expect(modal).toContainText(locale.importDiagnostics.tariff_new)
      await expect(modal).not.toContainText('Technical English')
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      if (language === 'de') await page.screenshot({ path: testInfo.outputPath(`vse-preview-${width}.png`), fullPage: true })
    }
    expect(errors).toEqual([])
  })
}
