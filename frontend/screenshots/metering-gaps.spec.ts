import { expect, test, type Page } from '@playwright/test'
import { mockApi, type ApiState } from './page-anatomy-fixtures'

test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })

async function qualityApi(page: Page, state: ApiState, gapCount = 5) {
  const errors = await mockApi(page, state)
  await page.route('**/api/v1/metering/readings/data-quality-status/**', route => {
    const params = new URL(route.request().url()).searchParams
    const scope = params.get('zev_id') ?? '42'
    const points = [{
      id: `mp${scope}`, meter_id: `CH-GAPS-${scope}`, participant_name: 'Historical Holder',
      severity: 'yellow', data_completeness: 77.4, days_with_data: 24, total_days: 31,
      gaps: [
        { start_date: '2026-10-02', end_date: '2026-10-02', duration_days: 1 },
        { start_date: '2026-10-04', end_date: '2026-10-05', duration_days: 2 },
        { start_date: '2026-10-07', end_date: '2026-10-07', duration_days: 1 },
        { start_date: '2026-10-09', end_date: '2026-10-09', duration_days: 1 },
        { start_date: '2026-10-11', end_date: '2026-10-12', duration_days: 2 },
      ].slice(0, gapCount), unassigned_days: 0, unassigned_readings: 0, assignment_overlap: false,
    }, {
      id: `mp${scope}-2`, meter_id: `CH-COMPLETE-${scope}`, participant_name: 'Current Holder',
      severity: 'green', data_completeness: 100, days_with_data: 31, total_days: 31,
      gaps: [], unassigned_days: 0, unassigned_readings: 0, assignment_overlap: false,
    }]
    return route.fulfill({ json: {
      date_from: params.get('date_from'), date_to: params.get('date_to'),
      metering_points: points.filter(point => !params.has('metering_point') || params.get('metering_point') === point.id),
    } })
  })
  return errors
}

for (const role of ['admin', 'manager', 'viewer'] as const) {
  test(`${role} inspects gaps and opens imports with the same filters`, async ({ page }, testInfo) => {
    const errors = await qualityApi(page, { role, populated: true, meterCount: 2 })
    // The manager run uses the legacy from/to period, the others the canonical one.
    const dates = role === 'manager' ? 'from=2026-10-01&to=2026-10-31' : 'period_start=2026-10-01&period_end=2026-10-31'
    const query = `${dates}&metering_point=mp42&quality_severity=yellow&extra=keep&tab=quality`
    await page.goto(`/metering/quality?${query}#details`)
    const trigger = page.getByRole('button', { name: '7 days, show gaps for CH-GAPS-42', exact: true })
    await expect(trigger).toHaveText('7 days')
    // Rows stay compact: the dates are only rendered in the dialog.
    await expect(page.locator('tbody')).not.toContainText('02.10.2026')

    for (const width of [1440, 400]) {
      await page.setViewportSize({ width, height: 900 })
      await trigger.focus()
      await page.keyboard.press('Enter')
      const dialog = page.getByRole('dialog', { name: 'Missing Days' })
      await expect(dialog).toBeVisible()
      await expect(dialog).toContainText('CH-GAPS-42')
      await expect(dialog).toContainText('Historical Holder')
      await expect(dialog).toContainText('01.10.2026 – 31.10.2026')
      await expect(dialog.locator('li')).toHaveCount(3)
      await expect(dialog).toContainText(role === 'viewer' ? 'Ask a manager to import' : 'Import a metering file')
      await expect(dialog.locator('li').first()).toHaveText('02.10.2026 1 day')
      await expect(dialog.locator('li').nth(1)).toHaveText('04.10.2026 – 05.10.2026 2 days')
      const more = dialog.getByRole('button', { name: 'And 2 more gaps' })
      await expect(more).toHaveAttribute('aria-expanded', 'false')
      await more.click()
      await expect(dialog.locator('li')).toHaveCount(5)
      await expect(dialog).toContainText('11.10.2026 – 12.10.2026')
      await dialog.getByRole('button', { name: 'Show fewer' }).click()
      await expect(dialog.locator('li')).toHaveCount(3)
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await expect(dialog).toBeInViewport({ ratio: 1 })
      await page.screenshot({ path: testInfo.outputPath(`gaps-${role}-${width}.png`), animations: 'disabled' })
      await more.click()
      await page.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
      await expect(trigger).toBeFocused()
    }

    await trigger.click()
    const dialog = page.getByRole('dialog', { name: 'Missing Days' })
    await expect(dialog.locator('li')).toHaveCount(3) // Reopening resets expansion.
    await dialog.getByRole('button', { name: 'Go to imports' }).click()
    const expectedParams = new URLSearchParams(query)
    expectedParams.delete('tab')
    await expect(page).toHaveURL(`/metering/imports?${expectedParams}#details`)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByRole('tab', { name: 'Import history', exact: true })).toHaveAttribute('aria-selected', 'true')
    if (role === 'viewer') await expect(page.getByRole('button', { name: 'New Import', exact: true })).toHaveCount(0)
    expect(errors).toEqual([])
  })
}

test('complete points have no dialog and filter/period changes dismiss old gaps', async ({ page }) => {
  const errors = await qualityApi(page, { populated: true, meterCount: 2 })
  await page.goto('/metering/quality?period_start=2026-10-01&period_end=2026-10-31')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  const complete = page.locator('tbody tr').filter({ hasText: 'CH-COMPLETE-42' })
  await expect(complete.getByRole('button', { name: /show gaps/ })).toHaveCount(0)
  await expect(complete.locator('td').last()).toHaveText('Complete')

  const trigger = page.getByRole('button', { name: /show gaps/ })
  for (const query of [
    'period_start=2026-10-01&period_end=2026-10-31&quality_severity=yellow',
    'period_start=2026-09-01&period_end=2026-09-30',
  ]) {
    await trigger.click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.evaluate(search => {
      history.replaceState(history.state, '', `/metering/quality?${search}`)
      dispatchEvent(new PopStateEvent('popstate'))
    }, query)
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  expect(errors).toEqual([])
})

test('a single gap still opens a dialog and Tab stays inside it', async ({ page }) => {
  const errors = await qualityApi(page, { populated: true }, 1)
  await page.goto('/metering/quality?period_start=2026-10-01&period_end=2026-10-31')
  const trigger = page.getByRole('button', { name: /show gaps/ })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Missing Days' })
  await expect(dialog.locator('li')).toHaveCount(1)
  await expect(dialog.getByRole('button', { name: /more gap/ })).toHaveCount(0)
  const close = dialog.getByRole('button', { name: 'Close' })
  await close.focus()
  await page.keyboard.press('Shift+Tab')
  await expect(dialog.getByRole('button', { name: 'Go to imports' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(close).toBeFocused()
  await close.click()
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  expect(errors).toEqual([])
})

test('removing the selected community closes gaps from the previous community', async ({ page }) => {
  const state: ApiState = {
    populated: true, zevs: [{ id: '42', name: 'First ZEV' }, { id: '43', name: 'Second ZEV' }],
  }
  const errors = await qualityApi(page, state)
  await page.goto('/metering/quality?period_start=2026-10-01&period_end=2026-10-31')
  await page.getByRole('button', { name: /show gaps/ }).click()
  await expect(page.getByRole('dialog')).toContainText('CH-GAPS-42')
  // Access can change while the dialog is open. Refreshing the available
  // communities reconciles selection without clicking through the modal.
  state.transitionScope = '42'
  state.zevs = [{ id: '43', name: 'Second ZEV' }]
  await page.evaluate(() => {
    for (const value of ['hidden', 'visible']) {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value })
      window.dispatchEvent(new Event('visibilitychange'))
    }
  })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('tbody')).toContainText('CH-GAPS-43')
  await page.getByRole('button', { name: /show gaps/ }).click()
  await expect(page.getByRole('dialog')).toContainText('CH-GAPS-43')
  await expect(page.getByRole('dialog')).not.toContainText('CH-GAPS-42')
  expect(errors).toEqual([])
})

test('a refetch that drops the selected point closes the dialog for good', async ({ page }) => {
  const errors = await qualityApi(page, { populated: true })
  let dropped = false
  await page.route('**/api/v1/metering/readings/data-quality-status/**', route => dropped
    ? route.fulfill({ json: { date_from: '2026-10-01', date_to: '2026-10-31', metering_points: [] } })
    : route.fallback())
  const refetch = () => page.evaluate(() => {
    for (const value of ['hidden', 'visible']) {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value })
      window.dispatchEvent(new Event('visibilitychange'))
    }
  })
  await page.goto('/metering/quality?period_start=2026-10-01&period_end=2026-10-31')
  await page.getByRole('button', { name: /show gaps/ }).click()
  await expect(page.getByRole('dialog')).toBeVisible()

  dropped = true
  await refetch()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  dropped = false
  await refetch()
  await expect(page.getByRole('button', { name: /show gaps/ })).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(errors).toEqual([])
})
