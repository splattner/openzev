import { expect, test } from '@playwright/test'
import { mockApi } from './page-anatomy-fixtures'

test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })

const period = 'period_start=2026-10-01&period_end=2026-10-31'
const readings = [
  { timestamp: '2026-10-25T00:00:00Z', energy_kwh: 0, condition: '' },
  { timestamp: '2026-10-25T01:00:00Z', energy_kwh: 2, condition: '56' },
].map(row => ({ ...row, direction: 'in', resolution: '15min', import_source: 'sdatch' }))

const held = Array.from({ length: 51 }, (_, index) => ({
  id: `held-${index}`, metering_point: index === 50 ? 'mp42-2' : 'mp42', meter_id: index === 50 ? 'METER-B' : 'METER-A',
  timestamp: index === 50 ? '2026-10-25T01:00:00Z' : new Date(Date.parse('2026-10-25T00:00:00Z') + index * 900_000).toISOString(),
  direction: 'in', energy_kwh: '9.0000', resolution: '15min', condition: '21',
  business_reason: 'E88', import_source: 'sdatch', import_batch: 'batch-42',
  source_document_id: `DOCUMENT-${'x'.repeat(30)}`, source_delivery_id: `DELIVERY-${'x'.repeat(55)}`, source_creation: '2026-10-26T00:00:00Z',
  created_at: '2026-10-26T01:00:00Z', accepted_energy_kwh: index === 50 ? null : '0.0000',
}))

for (const width of [1440, 400]) {
  test(`reading quality, held pagination and import provenance at ${width}px`, async ({ page }, testInfo) => {
    const errors = await mockApi(page, { role: 'viewer', populated: true })
    await page.setViewportSize({ width, height: 900 })
    await page.route('**/metering/readings/raw-data/**', route => route.fulfill({ json:
      new URL(route.request().url()).searchParams.has('date') ? readings : [
        { date: '2026-10-25', in_kwh: 2, out_kwh: 0, readings_count: 2 },
      ],
    }))
    const heldQueries: URLSearchParams[] = []
    let resolved = false
    await page.route('**/metering/held-readings/**', route => {
      const params = new URL(route.request().url()).searchParams
      heldQueries.push(params)
      const second = params.get('page') === '2'
      if (resolved) return route.fulfill({ json: { count: 0, page_size: 50, next: null, previous: null, results: [] } })
      const rows = second ? held.slice(50) : held.slice(0, 50)
      return route.fulfill({ json: {
        count: held.length, page_size: 50, next: second ? null : '?page=2', previous: second ? '?page=1' : null,
        results: params.has('import_batch') ? rows : rows.map(row => ({ ...row, meter_id: 'METER-A', metering_point: 'mp42' })),
      } })
    })
    await page.goto(`/metering/chart?${period}&metering_point=mp42`)
    const raw = page.locator('.raw-metering')
    await raw.locator('tr.raw-metering-day').click()
    await raw.getByRole('button', { name: /02:00, 2.0000 kWh/ }).click()
    await expect(raw.getByRole('region', { name: 'Interval detail' })).toContainText('25.10.2026 02:00 GMT+02:00')
    await expect(raw.getByRole('region', { name: 'Interval detail' })).toContainText('25.10.2026 02:00 GMT+01:00')
    await expect.poll(() => heldQueries.length).toBe(1)
    await raw.getByRole('button', { name: 'Show held observations' }).click()
    const panel = raw.locator('.held-readings')
    await expect(panel).toContainText('0.0000 kWh')
    await expect(panel).toContainText('DOCUMENT')
    if (width === 400) {
      const scroll = panel.getByRole('region', { name: 'Held observations', exact: true })
      await scroll.focus()
      await page.keyboard.press('ArrowRight')
      await expect.poll(() => scroll.evaluate(element => element.scrollLeft)).toBeGreaterThan(0)
    }
    expect(heldQueries[0].get('metering_point')).toBe('mp42')
    expect(heldQueries[0].get('date_from')).toBe('2026-10-01')
    expect(heldQueries[0].get('date_to')).toBe('2026-10-31')
    await panel.getByRole('button', { name: 'Next page' }).click()
    await expect(panel).toContainText('METER-A')
    await expect(panel).toContainText('No accepted reading')
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`quality-${width}.png`), fullPage: true })

    await page.route('**/metering/import-logs/**', route => route.fulfill({ json: {
      count: 1, next: null, previous: null, results: [{
        id: 'log-42', batch_id: 'batch-42', zev: '42', zev_name: 'Review ZEV',
        filename: 'held.xml', source: 'sdatch', created_at: '2026-10-26T00:00:00Z',
        rows_total: 51, rows_imported: 0, rows_overwritten: 0, rows_skipped: 0,
        errors: [], warnings: [], result_status: 'held', result_counts: { held: 51 }, issues: [],
      }],
    } }))
    await page.goto(`/metering/imports?${period}`)
    await page.getByRole('button', { name: 'Open protocol', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('METER-A')
    await expect(dialog).toContainText('Remaining held observations')
    expect(heldQueries.at(-1)?.get('import_batch')).toBe('batch-42')
    expect(heldQueries.at(-1)?.has('metering_point')).toBe(false)
    await dialog.getByRole('button', { name: 'Next page' }).click()
    await expect(dialog).toContainText('METER-B')
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`protocol-${width}.png`), fullPage: true })
    resolved = true
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await page.getByRole('button', { name: 'Open protocol', exact: true }).click()
    await expect(dialog).toContainText('No held observations from this import remain.')
    await expect(dialog).toContainText('51') // Historical accounting survives resolution.
    const emptyHeld = page.waitForResponse('**/metering/held-readings/**')
    await page.goto(`/metering/chart?${period}&metering_point=mp42`)
    await (await emptyHeld).finished()
    await expect(raw.locator('tr.raw-metering-day')).toBeVisible()
    await expect(raw.locator('.held-readings')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath(`no-held-${width}.png`), fullPage: true })
    expect(errors).toEqual([])
  })
}

test('a held-only period remains inspectable without an accepted day', async ({ page }) => {
  const errors = await mockApi(page, { role: 'manager', populated: true })
  await page.route('**/metering/held-readings/**', route => route.fulfill({ json: {
    count: 1, page_size: 50, next: null, previous: null, results: [{ ...held[50], meter_id: 'METER-A' }],
  } }))
  await page.goto(`/metering/chart?${period}&metering_point=mp42`)
  await expect(page.locator('.raw-metering')).toContainText('No raw metering readings')
  await page.getByRole('button', { name: 'Show held observations' }).click()
  await expect(page.locator('.held-readings')).toContainText('No accepted reading')
  expect(errors).toEqual([])
})
