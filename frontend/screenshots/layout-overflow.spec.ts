import { test, expect, type Page } from '@playwright/test'
import { API_BASE, getAdminToken, navigateTo } from './helpers'

const PROBE_PREFIX = 'Layout Probe '
const PROBE_COUNT = 10

async function prepareProbeZevs(page: Page) {
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  const meResp = await page.request.get(`${API_BASE}/auth/me/`, { headers })
  expect(meResp.ok(), `Fetching /auth/me/ failed (${meResp.status()})`).toBeTruthy()
  const user = await meResp.json()
  const results = Array.from({ length: PROBE_COUNT }, (_, index) => ({
    id: `layout-probe-${index + 1}`,
    name: `${PROBE_PREFIX}${String(index + 1).padStart(2, '0')}`,
    owner: user.id,
  }))
  await page.route(/\/api\/v1\/zev\/zevs\/(?:\?.*)?$/, (route) => route.fulfill({
    json: { count: results.length, next: null, previous: null, results },
  }))
  // Selection stays local to this browser, including the saved preference.
  await page.route(/\/api\/v1\/auth\/me\/$/, (route) => {
    if (route.request().method() !== 'PATCH') return route.continue()
    return route.fulfill({ json: { ...user, ...route.request().postDataJSON() } })
  })
}

test('a long community list scrolls inside its menu and stays on screen', async ({ page }) => {
  await prepareProbeZevs(page)
  await navigateTo(page, '/tariffs')
  const switcher = page.locator('main .community-switch')
  for (const size of [
    { width: 1440, height: 600 },
    { width: 1280, height: 400 },
    { width: 740, height: 390 },
    { width: 390, height: 600 },
  ]) {
    await page.setViewportSize(size)
    await switcher.click()
    const menu = page.locator('.community-menu')
    await expect(menu).toBeVisible()
    const box = await menu.boundingBox()
    expect(box, 'community menu has no box').not.toBeNull()
    expect(box!.y, 'menu starts above the viewport').toBeGreaterThanOrEqual(0)
    expect(box!.y + box!.height, 'menu ends below the viewport').toBeLessThanOrEqual(size.height)
    expect(box!.x + box!.width, 'menu ends right of the viewport').toBeLessThanOrEqual(size.width)
    expect(box!.height, 'community menu was crushed').toBeGreaterThanOrEqual(100)
    if (size.height <= 400) {
      expect(await menu.evaluate((el) => el.scrollHeight > el.clientHeight), 'the list scrolls inside the menu').toBe(true)
    }
    const target = page.getByRole('menuitem', { name: `${PROBE_PREFIX}10` })
    await target.scrollIntoViewIfNeeded()
    await target.click()
    await expect(menu).toBeHidden()
    await expect(switcher).toContainText(`${PROBE_PREFIX}10`)
  }
})

async function prepareFocusPage(page: Page, width = 1366) {
  await page.setViewportSize({ width, height: 800 })
  await page.addInitScript(() => {
    localStorage.setItem('openzev.sidebarCollapsed', 'true')
    localStorage.setItem('openzev.language', 'en')
  })
  await navigateTo(page, '/account')
}

test('breakpoint changes preserve body focus outside navigation', async ({ page }) => {
  await prepareFocusPage(page, 400)
  expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true)
  await page.setViewportSize({ width: 1366, height: 768 })
  await expect(page.locator('.shell-collapsed')).toBeVisible()
  expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true)
})

test('breakpoint changes recover focus from hidden navigation controls', async ({ page }) => {
  await prepareFocusPage(page)
  const collapse = page.locator('.sidebar-collapse-button')
  const hamburger = page.locator('.mobile-menu-button')
  await collapse.focus()
  await page.setViewportSize({ width: 400, height: 800 })
  await expect(collapse).toBeHidden()
  await expect(hamburger).toBeFocused()
  await hamburger.press('Enter')
  await expect(page.locator('.sidebar.mobile-open')).toBeVisible()
  await expect(page.locator('#app-sidebar')).toBeInViewport({ ratio: 0.95 })
  await page.keyboard.press('Shift+Tab')
  await expect(page.locator('.sidebar-footer .user-menu-trigger')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(hamburger).toBeFocused()
  await expect(page.locator('#app-sidebar')).not.toBeInViewport()
  await page.setViewportSize({ width: 1366, height: 768 })
  await expect(collapse).toBeFocused()
  await expect(collapse).toBeVisible()
  await expect(page.locator('.sidebar.mobile-open')).toHaveCount(0)
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden')
  await expect(page.locator('nav a[href="/admin/system-settings"]')).toHaveAccessibleName('Platform: Settings')
  expect(await page.evaluate(() => localStorage.getItem('openzev.sidebarCollapsed'))).toBe('true')
})

test('breakpoint changes preserve a textbox value, focus and selection', async ({ page }) => {
  await prepareFocusPage(page)
  const input = page.locator('input[name="first_name"]')
  await input.fill('Unsaved profile name')
  await input.evaluate((node: HTMLInputElement) => node.setSelectionRange(2, 8))
  for (const width of [400, 1366]) {
    await page.setViewportSize({ width, height: 800 })
    if (width === 400) await expect(page.locator('.sidebar-collapse-button')).toBeHidden()
    else await expect(page.locator('.sidebar-collapse-button')).toBeVisible()
    await expect(input).toBeFocused()
    await expect(input).toHaveValue('Unsaved profile name')
    expect(await input.evaluate((node: HTMLInputElement) => [node.selectionStart, node.selectionEnd])).toEqual([2, 8])
  }
})
