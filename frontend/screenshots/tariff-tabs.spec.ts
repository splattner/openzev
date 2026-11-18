import { expect, test } from '@playwright/test'
import { apiErrors, mockApi } from './page-anatomy-fixtures'
import type { TariffProgression } from '../src/types/api'

test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })

test.beforeEach(async ({ page }) => {
  await mockApi(page, { populated: true })
  await page.route('**/api/v1/tariffs/tariffs/progression/**', route => {
    const params = new URL(route.request().url()).searchParams
    const progression: TariffProgression = {
      zev: '42', energy_type: params.get('energy_type') === 'local' ? 'local' : 'grid',
      vat_mode: 'not_registered', from: '2026-01-01', to: '2027-01-01',
      expected_categories: [], lines: [], intervals: [], fixed_fees: [],
    }
    return route.fulfill({ json: progression })
  })
})

test.afterEach(({ page }) => expect(apiErrors.get(page) ?? []).toEqual([]))

test('filters preserve pane history, selection and URL context across tabs', async ({ page }) => {
  await page.goto('/dashboard')
  await page.locator('#app-sidebar a[href="/tariffs"]').click()
  await page.getByRole('button', { name: 'Tariff 42', exact: true }).click()
  const selected = new URL(page.url()).searchParams
  await page.getByRole('tab', { name: 'Price progression' }).click()
  await page.locator('.tariff-progression-controls select').selectOption('local')
  await page.getByRole('tab', { name: 'Tariff components' }).click()
  await expect(page.locator('.detail-pane')).toBeVisible()
  const returned = new URL(page.url()).searchParams
  expect(returned.get('tariff')).toBe(selected.get('tariff'))
  expect(returned.get('version')).toBe(selected.get('version'))
  expect(returned.get('energy')).toBe('local')
  await page.getByRole('tab', { name: 'Price progression' }).click()
  await expect(page.locator('.tariff-progression-controls select')).toHaveValue('local')
  await page.getByRole('tab', { name: 'Tariff components' }).click()
  await page.locator('.detail-pane header').getByRole('button', { name: 'Close', exact: true }).click()
  await expect(page).toHaveURL(/\/tariffs$/)
  await expect(page.locator('.detail-pane')).toHaveCount(0)
  await page.goBack()
  await expect(page).toHaveURL(/\/dashboard$/)
  await page.goForward()
  await expect(page).toHaveURL(/\/tariffs$/)
  await expect(page.locator('.detail-pane')).toHaveCount(0)
  await page.goForward()
  await expect(page.locator('.detail-pane')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('version')).toBe(selected.get('version'))
})

test('keyboard switches retain filters and hash without replaying focus after reload', async ({ page }, testInfo) => {
  await page.goto('/tariffs?energy=local&from=2026-01-01#context')
  const components = page.getByRole('tab', { name: 'Tariff components' })
  const progression = page.getByRole('tab', { name: 'Price progression' })
  await components.focus()
  await page.keyboard.press('ArrowRight')
  await expect(page).toHaveURL(/\/tariffs\/progression\?energy=local&from=2026-01-01#context$/)
  await expect(progression).toBeFocused()
  await expect(progression).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.empty-state')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tariffs')
  await expect(page.getByRole('link', { name: 'Back to tariffs' })).toHaveCount(0)
  const energy = page.locator('.tariff-progression-controls select')
  await energy.selectOption('grid')
  await expect(page).toHaveURL(/energy=grid&from=2026-01-01#context$/)
  await energy.focus()
  await page.reload()
  await expect(progression).toHaveAttribute('aria-selected', 'true')
  await expect(page.locator('.empty-state')).toBeVisible()
  await expect(progression).not.toBeFocused()
  await expect(energy).toHaveValue('grid')
  await progression.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(components).toBeFocused()
  await expect(page).toHaveURL(/\/tariffs\?energy=grid&from=2026-01-01#context$/)
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(components).toBeVisible()
    await expect(progression).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`tariff-tabs-${width}.png`), fullPage: true })
  }
})

test('keyboard draft guard keeps edits on cancel and discards them on a real switch', async ({ page }) => {
  await page.goto('/tariffs')
  await page.getByRole('button', { name: 'Tariff 42', exact: true }).click()
  await page.locator('.detail-pane').getByRole('button', { name: 'Edit', exact: true }).click()
  const notes = page.locator('.tariff-pane-form textarea')
  await notes.fill('Unsaved draft')
  const components = page.getByRole('tab', { name: 'Tariff components' })
  const progression = page.getByRole('tab', { name: 'Price progression' })
  await components.focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: 'Keep editing', exact: true }).click()
  await expect(progression).toBeFocused()
  await expect(notes).toHaveValue('Unsaved draft')
  await page.keyboard.press('ArrowLeft')
  await expect(components).toBeFocused()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.keyboard.press('ArrowRight')
  await page.getByRole('button', { name: 'Discard', exact: true }).click()
  await expect(page).toHaveURL(/\/tariffs\/progression\?/)
  await expect(progression).toBeFocused()
  await page.keyboard.press('ArrowLeft')
  await expect(components).toBeFocused()
  await page.locator('.detail-pane').getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(notes).toHaveValue('')
})

test('a cold progression route can be left by keyboard before its code loads', async ({ page }) => {
  let release!: () => void
  let intercepted = false
  const pending = new Promise<void>(resolve => { release = resolve })
  await page.route('**/TariffProgressionPage*', async route => {
    intercepted = true
    await pending
    await route.continue()
  })
  try {
    await page.goto('/tariffs')
    const components = page.getByRole('tab', { name: 'Tariff components' })
    const progression = page.getByRole('tab', { name: 'Price progression' })
    await components.focus()
    await page.keyboard.press('ArrowRight')
    await expect.poll(() => intercepted).toBe(true)
    await expect(progression).toHaveAttribute('aria-selected', 'true')
    await expect(progression).toBeFocused()
    await page.keyboard.press('ArrowLeft')
    await expect(page).toHaveURL(/\/tariffs$/)
    await expect(components).toBeFocused()
    await expect(components).toHaveAttribute('aria-selected', 'true')
    release()
    await page.keyboard.press('ArrowRight')
    await expect(page).toHaveURL(/\/tariffs\/progression$/)
    await expect(progression).toHaveAttribute('aria-selected', 'true')
    await expect(progression).toBeFocused()
  } finally { release() }
})
