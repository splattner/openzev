import { expect, test } from '@playwright/test'
import { navigateTo, pinDemoZev } from './helpers'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('openzev.language', 'en'))
  expect(await pinDemoZev(page)).toBe(true)
  await navigateTo(page, '/metering/points')
})

const rowMenu = (page: import('@playwright/test').Page) =>
  page.locator('.metering-point-row').first().locator('button.button[aria-haspopup="menu"]')

test('a dialog opened with the mouse from a row menu returns focus to its trigger', async ({ page }) => {
  const trigger = rowMenu(page)
  await trigger.click()
  await page.getByRole('menuitem', { name: 'Edit', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

test('Escape closes a row menu and returns focus to its trigger', async ({ page }) => {
  const trigger = rowMenu(page)
  await trigger.focus()
  await trigger.press('Enter')
  await expect(page.getByRole('menu')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('menu')).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

test('a row menu taller than a short viewport scrolls instead of running off screen', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 260 })
  await rowMenu(page).click()
  const menu = page.getByRole('menu')
  await expect(menu).toBeVisible()
  const box = await menu.boundingBox()
  expect(box!.y, 'menu starts above the viewport').toBeGreaterThanOrEqual(0)
  expect(box!.y + box!.height, 'menu ends below the viewport').toBeLessThanOrEqual(260)
  expect(await menu.evaluate((el) => el.scrollHeight > el.clientHeight), 'the entries scroll inside the menu').toBe(true)
})
