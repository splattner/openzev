import { expect, test } from '@playwright/test'
import { apiErrors, mockApi } from './page-anatomy-fixtures'

test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })
test.afterEach(({ page }) => expect(apiErrors.get(page) ?? []).toEqual([]))

for (const width of [1440, 400]) {
  test(`inline links and issue controls retain visible cues at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await mockApi(page, { qualityPeriod: ['2026-09-02', '2026-10-01'] })
    await page.route('**/api/v1/zev/metering-points/**', route => route.fulfill({ json: {
      count: 2, next: null, previous: null,
      results: [1, 0].map((readingCount, index) => ({
        id: index ? 'mp42-2' : 'mp42', zev: '42', meter_id: `MP-${index + 1}`,
        meter_type: 'consumption', is_active: true, reading_count: readingCount,
        has_behind_meter_generation: false, assignment_count: 0,
        first_reading_at: null, last_reading_at: null,
      })),
    } }))
    await page.goto('/metering/points')
    await page.mouse.move(0, 0)
    const error = page.getByRole('link', { name: 'Metering point MP-1: Data at risk – view data quality', exact: true })
    const warning = page.getByRole('link', { name: 'Metering point MP-2: No readings – view data quality', exact: true })
    const button = page.getByRole('button', { name: 'No current assignment', exact: true })
    for (const issue of [error, warning, button]) {
      await expect(issue).toBeVisible()
      await expect(issue.locator('span')).toHaveCSS('text-decoration-line', 'underline')
      const color = await issue.evaluate(element => getComputedStyle(element).color)
      await issue.hover()
      await expect(issue).toHaveCSS('color', color)
      await page.mouse.move(0, 0)
      // Reach each control through the tab order; never force focus onto it.
      for (let tabs = 0; tabs < 100 && !await issue.evaluate(element => element === document.activeElement); tabs++) {
        await page.keyboard.press('Tab')
      }
      await expect(issue).toBeFocused()
      await expect(issue).toHaveCSS('color', color)
      await expect(issue).toHaveCSS('outline-style', 'solid')
      await expect(issue).toHaveCSS('outline-width', '2px')
      await expect(issue).toHaveCSS('outline-offset', '2px')
      await expect(issue).toHaveCSS('outline-color', 'rgb(31, 92, 58)')
    }
    await page.screenshot({ path: testInfo.outputPath(`issue-focus-${width}.png`), fullPage: true })
    await page.getByRole('button', { name: 'Show details of MP-2', exact: true }).click()
    const ordinary = page.locator('.metering-point-detail').getByRole('link', { name: 'No data yet', exact: true })
    await page.mouse.move(0, 0)
    await expect(ordinary).toHaveCSS('text-decoration-line', 'underline')
  })
}
