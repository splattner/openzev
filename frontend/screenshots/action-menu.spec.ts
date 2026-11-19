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

for (const focus of ['trigger', 'item']) {
  test(`Escape closes a row menu and returns focus to its trigger, focus=${focus}`, async ({ page }) => {
    const trigger = rowMenu(page)
    await trigger.focus()
    await expect(page.getByRole('tooltip')).toHaveText((await trigger.getAttribute('aria-label'))!)
    await trigger.press('Enter')
    await expect(page.getByRole('menu')).toBeVisible()
    await expect(page.getByRole('menuitem', { name: 'Delete data', exact: true })).toHaveClass(/action-menu-item-danger/)
    const escapeTarget = focus === 'trigger' ? trigger : page.getByRole('menuitem', { name: 'Edit', exact: true })
    await escapeTarget.focus()
    await expect(escapeTarget).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('menu')).toHaveCount(0)
    await expect(trigger).toBeFocused()
  })
}

for (const width of [1440, 400]) {
  test(`metering row controls are reachable with the keyboard at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const actions = page.locator('.metering-point-actions').first()
    const chart = actions.getByRole('link', { name: /Chart/ })
    const expand = actions.getByRole('button', { name: /details/i })
    await chart.focus()
    await expect(page.getByRole('tooltip')).toHaveText((await chart.getAttribute('aria-label'))!)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('tooltip')).toHaveCount(0)
    await expect(chart).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(rowMenu(page)).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(expand).toBeFocused()
    await expect(expand).toBeInViewport()
    await expect(page.getByRole('tooltip', { name: (await expand.getAttribute('aria-label'))!, exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`metering-controls-${width}.png`), animations: 'disabled' })
  })

  test(`assignment Edit and Remove are named icons in that order at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const row = page.locator('.metering-point-card').filter({ hasText: 'CH-DEMO-CONS-0001' }).first()
    await row.locator('.metering-point-expand').click()
    await expect(page.getByRole('button', { name: 'Add assignment', exact: true })).toHaveClass(/button-secondary/)
    await expect(page.getByRole('button', { name: 'Add assignment', exact: true })).not.toHaveClass(/button-icon/)
    const actions = page.locator('.metering-assignment-actions').first()
    const buttons = actions.getByRole('button')
    await expect(buttons).toHaveCount(2)
    await expect(buttons.nth(0)).toHaveAccessibleName('Edit: Anna Consumer')
    await expect(buttons.nth(1)).toHaveAccessibleName('Remove assignment for Anna Consumer')
    await expect(buttons.nth(0)).toHaveText('')
    await expect(buttons.nth(1)).toHaveText('')
    await buttons.nth(0).focus()
    await page.keyboard.press('Tab')
    await expect(buttons.nth(1)).toBeFocused()
    await expect(page.getByRole('tooltip', { name: 'Remove assignment for Anna Consumer', exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`assignment-actions-${width}.png`), animations: 'disabled' })
    await buttons.nth(1).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('Anna Consumer')
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(buttons.nth(1)).toBeFocused()
  })
}

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
