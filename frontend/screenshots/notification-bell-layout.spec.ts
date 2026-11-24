import { expect, test, type Locator } from '@playwright/test'
import { apiErrors, mockApi } from './page-anatomy-fixtures'

test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })

test.afterEach(({ page }) => expect(apiErrors.get(page)).toEqual([]))

const longName = `Solar community ${'W'.repeat(184)}`

async function expectAligned(row: Locator, bell: Locator) {
  const scope = await row.boundingBox()
  const trigger = await bell.boundingBox()
  expect(scope).not.toBeNull()
  expect(trigger).not.toBeNull()
  const verticalOffset = trigger!.y + trigger!.height / 2 - scope!.y - scope!.height / 2
  expect(Math.abs(verticalOffset)).toBeLessThan(1)
}

test('a wrapped plain community name shares a row with the bell', async ({ page }, testInfo) => {
  await mockApi(page, { role: 'viewer', zevs: [{ id: '42', name: longName }] })
  await page.setViewportSize({ width: 769, height: 860 })
  await page.goto('/dashboard')
  const row = page.locator('main .page-header-scope')
  const bell = row.getByRole('button', { name: 'Notifications' })
  await expect(bell).toBeVisible()
  await expect(row.getByRole('button')).toHaveCount(1)
  await expect(row.locator('.eyebrow-note')).toContainText('Viewer (read only)')
  expect((await row.boundingBox())!.height).toBeGreaterThan((await bell.boundingBox())!.height)
  await expectAligned(row, bell)
  const title = await page.locator('main h1').boundingBox()
  const scope = await row.boundingBox()
  expect(title!.y).toBeGreaterThanOrEqual(scope!.y + scope!.height)
  await page.screenshot({ path: testInfo.outputPath('wrapped-community.png') })
})

test('the switcher and bell are operable at the desktop boundary and the bell moves to the mobile bar', async ({ page }, testInfo) => {
  await mockApi(page, { role: 'viewer', zevs: [{ id: '42', name: longName }, { id: '43', name: 'Second ZEV' }] })
  await page.route('**/api/v1/notifications/unread-count/', route => route.fulfill({ json: { count: 1 } }))
  await page.route('**/api/v1/notifications/', route => route.fulfill({ json: {
    count: 1, next: null, previous: null, results: [{
      id: 'n1', type: 'import.failed', audience: 'manager', zev: '42', zev_name: longName,
      payload: { issues: 1, rows_skipped: 3 }, target_type: 'import_log', target_id: 'log-1',
      created_at: '2026-10-02T10:00:00Z', read_at: null,
    }],
  } }))
  await page.setViewportSize({ width: 769, height: 860 })
  await page.goto('/dashboard')

  const row = page.locator('main .page-header-scope')
  const bell = page.locator('.notification-bell-trigger')
  const switcher = row.locator('.community-switch')
  const panel = page.locator('.notification-panel')
  const menu = page.locator('.community-menu')
  await expect(row.locator('.notification-bell-trigger')).toBeVisible()
  await expect(bell).toHaveCount(1)
  await expect(bell.locator('.notification-bell-badge')).toHaveText('1')
  await expect(row.locator('.eyebrow-note')).toContainText('Viewer (read only)')
  await expectAligned(row, bell)

  await switcher.click()
  await expect(menu).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(switcher).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(bell).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(panel).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(panel.getByRole('button', { name: 'Mark all as read' })).toBeFocused()
  await expect(panel.locator('.notification-item')).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(panel.locator('.notification-item')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(panel).toBeHidden()
  await expect(bell).not.toBeFocused()

  await bell.click()
  await expect(panel).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  await expect(bell).toBeFocused()

  for (const width of [768, 320]) {
    await page.setViewportSize({ width, height: 860 })
    const banner = page.getByRole('banner')
    await expect(banner.locator('.notification-bell-trigger')).toBeVisible()
    await expect(banner).toHaveCSS('position', 'sticky')
    await expect(bell).toHaveCount(1)
    await bell.click()
    await expect(panel).toBeVisible()
    const box = (await panel.boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(width)
    expect(await banner.evaluate(element => element.scrollWidth)).toBe(width)
    if (width === 320) await page.screenshot({ path: testInfo.outputPath('mobile-panel.png') })
    await page.keyboard.press('Escape')
    await expect(bell).toBeFocused()
  }
})

test('My metering points aligns a plain scope and Account retains a separate bell row', async ({ page }) => {
  await mockApi(page, { role: 'participant' })
  await page.route('**/api/v1/metering/supplementary/sources/', route => route.fulfill({
    json: { count: 0, next: null, previous: null, results: [] },
  }))
  await page.goto('/me/metering-points')
  const row = page.locator('main .page-header-scope')
  const bell = page.locator('.notification-bell-trigger')
  await expect(row.locator('.notification-bell-trigger')).toBeVisible()
  await expect(row.getByRole('button')).toHaveCount(1)
  await expectAligned(row, bell)

  await page.locator('.user-menu-trigger').click()
  await page.locator('#user-menu-list').getByRole('link', { name: 'Account' }).click()
  await expect(page).toHaveURL(/\/account$/)
  await expect(page.getByRole('banner').locator('.notification-bell-trigger')).toBeVisible()
  await expect(bell).toHaveCount(1)
  const title = await page.locator('main h1').boundingBox()
  const trigger = (await bell.boundingBox())!
  expect(title!.y).toBeGreaterThan(trigger.y + trigger.height)
  await page.setViewportSize({ width: 320, height: 860 })
  await expect(page.getByRole('banner')).toHaveCSS('position', 'sticky')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320)
})
