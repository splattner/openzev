import { expect, test, type Page } from '@playwright/test'
import { apiErrors, mockApi } from './page-anatomy-fixtures'
import type { TariffPeriod, TariffSeries, TariffVersion } from '../src/types/api'

test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })
test.afterEach(({ page }) => expect(apiErrors.get(page) ?? []).toEqual([]))

function band(id: string, price: string, overrides: Partial<TariffPeriod> = {}): TariffPeriod {
  return { id, tariff: 'current', period_type: 'flat', label: '', price_chf_per_kwh: price,
    percentage: null, time_from: null, time_to: null, weekdays: '', months: '', ...overrides }
}

const current: TariffVersion = {
  id: 'current', zev: '42', name: 'Grid', category: 'energy', billing_mode: 'energy', energy_type: 'grid',
  valid_from: '2026-01-01', valid_to: '2026-12-31', fixed_price_chf: null, split_key: 'equal', notes: '',
  periods: [band('flat', '0.295')],
}
const next: TariffVersion = { ...current, id: 'next', valid_from: '2027-01-01', valid_to: '2027-12-31',
  periods: [band('next-flat', '0.315', { tariff: 'next' })] }
const later: TariffVersion = { ...next, id: 'later', valid_from: '2028-01-01', valid_to: null,
  periods: [band('later-flat', '0.350', { tariff: 'later' })] }
const grid: TariffSeries = { zev: '42', name: 'Grid', category: 'energy', billing_mode: 'energy',
  energy_type: 'grid', version_count: 3, active_version_id: 'current', gaps: [], versions: [later, next, current] }

async function tariffs(page: Page, series: TariffSeries[]) {
  await mockApi(page)
  await page.route('**/api/v1/tariffs/tariffs/series/**', route => route.fulfill({ json: series }))
}

test('the next version is read from the current row and opens through the URL and keyboard', async ({ page }) => {
  await tariffs(page, [grid])
  await page.goto('/tariffs')
  const row = page.getByRole('region', { name: 'Current' })
  await expect(row.locator('td.numeric')).toContainText('0.295')
  // One row for the tariff: the next version is a line in it, not a second group.
  await expect(page.getByRole('region', { name: 'Upcoming' })).toHaveCount(0)
  const next = row.locator('.tariff-next-change')
  await expect(next).toHaveText('From 01.01.2027: 0.315 per kWh (+6.8 %)')
  for (const key of ['Enter', 'Space']) {
    await next.focus()
    await page.keyboard.press(key)
    await expect(page).toHaveURL(/version=next/)
    await expect(page.locator('.tariff-version-card.is-shown')).toContainText('0.315')
    await expect(page.locator('.tariff-version-card.is-shown .badge').first()).toHaveText('Upcoming')
    await expect(row.locator('tr.is-selected')).toHaveCount(1)
    // Every version in force or scheduled is in the pane, each with the change against the one before it.
    await expect(page.locator('.tariff-version-card')).toHaveCount(3)
    await expect(page.locator('.tariff-version-card').nth(1).locator('.tariff-change')).toContainText('+0.02')
    await page.locator('.detail-pane header').getByRole('button', { name: 'Close', exact: true }).click()
    await expect(page.locator('.detail-pane')).toBeHidden()
  }
})

test('active clicks and a bare link use the current version despite a stale active ID', async ({ page }) => {
  await tariffs(page, [{ ...grid, active_version_id: 'later' }])
  await page.goto('/tariffs?tariff=42%3AGrid')
  await expect(page.locator('.tariff-version-card.is-shown')).toContainText('0.295')
  await expect(page.locator('.detail-pane .info-banner')).toHaveCount(0)
  await page.locator('.detail-pane header').getByRole('button', { name: 'Close', exact: true }).click()
  await page.getByRole('region', { name: 'Current' }).locator('.tariff-select').click()
  await expect(page).toHaveURL(/version=current/)
  await expect(page.locator('.tariff-version-card.is-shown')).toContainText('0.295')
})

for (const language of ['en', 'de', 'fr']) {
  test(`narrow bands retain explanations and accessible headers in ${language}`, async ({ page }, testInfo) => {
    const percentage: TariffVersion = { ...current, id: 'percentage', name: 'Local', billing_mode: 'percentage_of_energy', energy_type: 'local',
      periods: [band('share', '0.000', { percentage: '60', price_chf_per_kwh: null })],
      percentage_base_summary: { price_chf_per_kwh: '0.295', dynamic_status: 'partial', reference_date: '2026-06-15' } }
    const longBands: TariffVersion = { ...current, periods: [
      band('high', '123.45678', { period_type: 'high', weekdays: '0,1,2,3,4', months: '1,2,3,10,11,12', time_from: '07:00', time_to: '21:00' }),
      band('low', '0.180', { period_type: 'low', time_from: '21:00', time_to: '07:00' }),
    ] }
    const dynamic: TariffVersion = { ...current, id: 'dynamic', name: 'Dynamic', dynamic_source: 'source', periods: [],
      dynamic_price_summary: { average_chf_per_kwh: '-0.12345', status: 'partial', reference_from: '2026-06-01', reference_to: '2026-06-30' } }
    await tariffs(page, [
      { ...grid, versions: [longBands], version_count: 1 },
      { ...grid, name: 'Local', billing_mode: 'percentage_of_energy', energy_type: 'local', versions: [percentage], version_count: 1 },
      { ...grid, name: 'Dynamic', versions: [dynamic], version_count: 1 },
    ])
    await page.addInitScript(lang => localStorage.setItem('openzev.language', lang), language)
    await page.goto('/tariffs')
    const table = page.locator('.tariff-table')
    const partial = table.locator('tbody tr').filter({ hasText: 'Local' })
    const qualification = { en: 'incomplete base average', de: 'unvollständiger Basisdurchschnitt', fr: 'moyenne de base incomplète' }[language]!
    for (const width of [360, 400]) {
      await page.setViewportSize({ width, height: 850 })
      await expect(partial.locator('.tariff-table-band-applies')).toContainText(qualification)
      await expect(partial.locator('.tariff-table-band-price')).toBeVisible()
      await expect(partial.locator('td.numeric')).toBeHidden()
      expect(await partial.locator('.tariff-table-band').getAttribute('title')).toContain('0.177')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await expect(table.getByRole('columnheader')).toHaveCount(7)
      await expect(table.getByRole('columnheader').filter({ hasText: 'CHF' })).toHaveCount(2)
      const cell = partial.locator('td.tariff-table-bands')
      const header = page.locator(`#${await cell.getAttribute('headers')}`)
      await expect(header).toHaveAttribute('scope', 'col')
      await expect(header).toHaveRole('columnheader')
      for (const price of await table.locator('.tariff-table-band-price').all()) {
        const box = (await price.boundingBox())!
        expect(box.x + box.width).toBeLessThanOrEqual(width)
      }
      await expect(table.locator('.tariff-table-band-price').last()).toContainText('-0.123 CHF')
      await page.screenshot({ path: testInfo.outputPath(`tariffs-${language}-${width}.png`), fullPage: true })
    }
    const session = await page.context().newCDPSession(page)
    const { nodes } = await session.send('Accessibility.getFullAXTree')
    const headers = nodes.filter(node => !node.ignored && node.role?.value === 'columnheader')
    expect(headers).toHaveLength(7)
    expect(headers.filter(node => node.name?.value.includes('CHF'))).toHaveLength(2)
    await session.detach()
    await page.setViewportSize({ width: 1440, height: 900 })
    // Content widths immediately either side of the 56rem container query.
    for (const width of [895, 897]) {
      await page.locator('.tariff-list').evaluate((element, size) => {
        element.style.boxSizing = 'content-box'
        element.style.width = `${size}px`
      }, width)
      await expect(partial.locator('td.numeric')).toBeVisible({ visible: width > 896 })
      await expect(partial.locator('td.tariff-table-bands')).toBeVisible({ visible: width <= 896 })
      await page.screenshot({ path: testInfo.outputPath(`tariffs-${language}-container-${width}.png`), fullPage: true })
    }
  })
}

test('shared sticky headers and the light raw-metering grid survive fractional zoom', async ({ page }, testInfo) => {
  await mockApi(page, { populated: true })
  await page.route('**/api/v1/metering/readings/raw-data/**', route => {
    const detail = new URL(route.request().url()).searchParams.has('date')
    return route.fulfill({ json: detail
      ? [{ timestamp: '2026-10-01T05:00:00Z', direction: 'in', energy_kwh: 1, resolution: '15min', import_source: 'test' }]
      : [{ date: '2026-10-01', in_kwh: 1, out_kwh: 0, readings_count: 1 }] })
  })
  await page.goto('/metering/chart?metering_point=mp42')
  await page.locator('.raw-metering-day').click()
  const operational = page.locator('.raw-metering-days thead th').first()
  const light = page.locator('.raw-metering-grid thead th').nth(1)
  for (const zoom of ['1.1', '1.25']) {
    await page.locator('html').evaluate((element, value) => { element.style.zoom = value }, zoom)
    await operational.scrollIntoViewIfNeeded()
    expect(await operational.evaluate(element => getComputedStyle(element).position)).toBe('sticky')
    expect(await operational.evaluate(element => getComputedStyle(element, '::before').backgroundColor))
      .toBe(await operational.evaluate(element => getComputedStyle(element).backgroundColor))
    expect(await light.evaluate(element => getComputedStyle(element, '::before').content)).toBe('none')
    expect(await light.evaluate(element => getComputedStyle(element).backgroundColor))
      .not.toBe(await operational.evaluate(element => getComputedStyle(element).backgroundColor))
    await page.screenshot({ path: testInfo.outputPath(`metering-headers-zoom-${zoom}.png`), fullPage: true })
  }
  await page.locator('html').evaluate(element => { element.style.zoom = '1' })
  await page.goto('/billing/invoices')
  const sharedHeader = page.locator('main table thead th').first()
  await expect(sharedHeader).toBeVisible()
  await page.locator('html').evaluate(element => { element.style.zoom = '1.25' })
  expect(await sharedHeader.evaluate(element => getComputedStyle(element, '::before').backgroundColor))
    .toBe(await sharedHeader.evaluate(element => getComputedStyle(element).backgroundColor))
  await page.screenshot({ path: testInfo.outputPath('billing-header-zoom-1.25.png'), fullPage: true })
})

test('at 400px the list leaves the tab order and the accessibility tree while the pane is open, and X brings it back', async ({ page }) => {
  await tariffs(page, [grid])
  await page.setViewportSize({ width: 400, height: 850 })
  await page.goto('/tariffs?tariff=42%3AGrid')
  const pane = page.locator('.detail-pane')
  await expect(pane).toBeVisible()
  await expect(page.locator('.detail-split')).toHaveAttribute('data-layout', 'narrow')
  const list = page.locator('.detail-split-list')
  await expect(list).toBeHidden()
  await expect(list).toHaveAttribute('hidden', '')
  // Hidden content is neither focusable nor exposed: no tariff row button is reachable by Tab.
  const session = await page.context().newCDPSession(page)
  const { nodes } = await session.send('Accessibility.getFullAXTree')
  await session.detach()
  expect(nodes.filter(node => !node.ignored && node.role?.value === 'columnheader')).toHaveLength(0)
  const reached = new Set<string>()
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press('Tab')
    reached.add(await page.evaluate(() => document.activeElement?.closest('.detail-split-list') ? 'list' : 'other'))
  }
  expect(reached.has('list')).toBe(false)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await pane.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(pane).toBeHidden()
  await expect(list).toBeVisible()
  await expect(page).not.toHaveURL(/tariff=/)
})

test('the pane is not modal: no inert, no scroll lock, no focus trap, and Escape and Cancel put focus back', async ({ page }) => {
  await tariffs(page, [grid])
  await page.goto('/tariffs?tariff=42%3AGrid')
  const pane = page.locator('.detail-pane')
  await expect(pane).toBeVisible()
  await expect(page.locator('.detail-split')).toHaveAttribute('data-layout', 'wide')
  expect(await page.locator('[inert]').count()).toBe(0)
  expect(await pane.getAttribute('aria-modal')).toBeNull()
  expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).not.toBe('hidden')
  // Tab leaves the pane in both directions instead of cycling inside it.
  const leftPane = new Set<boolean>()
  for (let i = 0; i < 60; i++) {
    await page.keyboard.press('Tab')
    leftPane.add(await page.evaluate(() => !document.activeElement?.closest('.detail-pane')))
  }
  expect(leftPane.has(true)).toBe(true)

  const rename = pane.getByRole('button', { name: 'Rename', exact: true })
  await rename.focus()
  await page.keyboard.press('Enter')
  const field = pane.getByRole('textbox').first()
  // An untouched form: Escape returns to viewing (the pane stays) and focus goes back to Rename.
  await page.keyboard.press('Escape')
  await expect(pane.getByRole('textbox')).toHaveCount(0)
  await expect(pane).toBeVisible()
  await expect(rename).toBeFocused()
  // Cancel does the same.
  await rename.click()
  await pane.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(pane.getByRole('textbox')).toHaveCount(0)
  await expect(rename).toBeFocused()
  // A dirty form is guarded: Escape asks, keeping the draft; discarding returns to viewing; a second Escape closes the pane.
  await rename.click()
  await field.fill('Grid renamed')
  // The form reports its draft to the guard one render after the input; a person is never quicker than that.
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await page.keyboard.press('Escape')
  const guard = page.getByRole('alertdialog').or(page.getByRole('dialog')).filter({ hasText: 'Discard changes?' })
  await expect(guard).toBeVisible()
  await guard.getByRole('button', { name: 'Keep editing' }).click()
  await expect(field).toHaveValue('Grid renamed')
  await expect(pane).toBeVisible()
  await field.press('Escape')
  await guard.getByRole('button', { name: 'Discard' }).click()
  await expect(pane.getByRole('textbox')).toHaveCount(0)
  await expect(rename).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(pane).toBeHidden()
  await expect(page).not.toHaveURL(/tariff=/)
})
