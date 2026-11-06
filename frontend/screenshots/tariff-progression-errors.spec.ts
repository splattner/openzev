import { expect, test } from '@playwright/test'
import { mockApi } from './page-anatomy-fixtures'

test.use({ storageState: { cookies: [], origins: [] } })

test('progression errors show readable diagnostics without validation metadata', async ({ page }, testInfo) => {
  const errors = await mockApi(page)
  await page.route('**/api/v1/notifications/unread-count/', route => route.fulfill({ json: { count: 0 } }))
  await page.route('**/api/v1/metering/live/enabled/', route => route.fulfill({ json: { enabled: false } }))
  await page.route('**/api/v1/tariffs/tariffs/progression/**', route => route.fulfill({
    status: 400,
    json: {
      energy_type: ['Reworded server diagnostic.'],
      validation_errors: [{
        code: 'invalid_choice', field: 'energy_type', path: ['energy_type'], params: {},
        message: 'Reworded server diagnostic.',
      }],
    },
  }))
  await page.goto('/tariffs/progression')
  const notice = page.getByRole('alert')
  await expect(notice).toContainText('Energy type: Select a valid option.')
  await expect(notice).not.toContainText('validation_errors')
  await expect(notice).not.toContainText('invalid_choice')
  await expect(notice).not.toContainText('Reworded server diagnostic.')
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 })
    if (width === 400) await expect(page.locator('#app-sidebar')).not.toBeInViewport()
    await expect(notice).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`progression-error-${width}.png`), fullPage: true })
  }
  expect(errors.filter(error => error !== 'Failed to load resource: the server responded with a status of 400 (Bad Request)')).toEqual([])
})
