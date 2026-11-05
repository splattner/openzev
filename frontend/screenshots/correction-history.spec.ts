import { expect, test } from '@playwright/test'
import { mockApi } from './page-anatomy-fixtures'
import type { ImportLog, SdatReadingChange } from '../src/types/api'

test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })

const log: ImportLog = {
  id: 'correction-42', batch_id: 'batch-42', zev: '42', zev_name: 'Review ZEV',
  filename: 'replacement.xml', source: 'sdatch', created_at: '2026-10-26T00:00:00Z',
  rows_total: 10_001, rows_imported: 0, rows_overwritten: 10_001, rows_skipped: 0,
  errors: [], warnings: [], result_status: 'accepted', issues: [],
  result_counts: {
    created: 0, overwritten: 10_001, held: 0, promoted: 1, duplicate: 0,
    stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
    reading_changes_truncated: true,
  },
  source_delivery: {
    delivery_id: 'REPLACEMENT-DELIVERY', creation: '2026-10-26T00:00:00Z', status: '5', reason: 'E88',
    sender_id: 'DSO', sender_role: 'MDR', receiver_id: 'OPENZEV', receiver_role: 'DEC',
  },
}
const changes: SdatReadingChange[] = Array.from({ length: 51 }, (_, index) => ({
  metering_point: 'mp42', meter_id: `CH-CORRECTION-${index}`, direction: 'in', kind: 'value',
  timestamp: new Date(Date.parse('2026-10-25T00:00:00Z') + index * 900_000).toISOString(),
  old_energy: index === 0 ? null : '0.0000', new_energy: '1.2345', promoted: index === 0,
  source_document_id: `DOC-${'x'.repeat(31)}`,
}))

for (const width of [1440, 400]) {
  test(`correction deep link, bounded history and keyboard scrolling at ${width}px`, async ({ page }, testInfo) => {
    const errors = await mockApi(page, { role: 'viewer', populated: true })
    await page.route('**/metering/live/enabled/', route => route.fulfill({ json: { enabled: false } }))
    await page.setViewportSize({ width, height: 900 })
    await page.route('**/metering/import-logs/', route => route.fulfill({ json: {
      count: 1, next: null, previous: null, results: [log],
    } }))
    let detailReads = 0
    await page.route('**/metering/import-logs/correction-42/', route => {
      detailReads += 1
      return route.fulfill({ json: { ...log, reading_changes: changes } })
    })
    await page.goto('/metering/imports?import=correction-42&change_from=2026-10-25&change_to=2026-10-26&keep=yes#correction-history')
    const section = page.locator('#correction-history')
    await expect(section).toBeFocused()
    await expect.poll(async () => {
      const heading = await section.getByRole('heading', { name: 'Reading changes' }).boundingBox()
      const header = await page.locator('.form-modal-header').boundingBox()
      return !!heading && !!header && heading.y >= header.y + header.height
    }).toBe(true)
    await expect(section).toContainText('Affected period: 25.10.2026–26.10.2026.')
    await expect(section).toContainText('51 changes retained.')
    await expect(section).toContainText('some changes were not retained')
    const scroll = section.getByRole('region', { name: 'Reading changes table' })
    await scroll.focus()
    await page.keyboard.press('ArrowRight')
    await expect.poll(() => scroll.evaluate(element => element.scrollLeft)).toBeGreaterThan(0)
    await section.getByRole('button', { name: 'Next page' }).click()
    await expect(section).toContainText('2 / 2')
    await expect(section.locator('tbody tr').first()).toContainText('CH-CORRECTION-50')
    expect(detailReads).toBe(1)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`corrections-${width}.png`) })
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(new URL(page.url()).searchParams.has('import')).toBe(false)
    expect(new URL(page.url()).searchParams.has('change_from')).toBe(false)
    expect(new URL(page.url()).searchParams.has('change_to')).toBe(false)
    expect(new URL(page.url()).searchParams.get('keep')).toBe('yes')
    expect(new URL(page.url()).hash).toBe('')
    expect(errors).toEqual([])
  })
}
