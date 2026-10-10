import { expect, test } from '@playwright/test'
import { mockApi, type ApiState } from './page-anatomy-fixtures'

test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })

test('dashboard custom period links survive reload/back and edits retain query/hash', async ({ page }, testInfo) => {
  const state: ApiState = { period: ['2026-02-12', '2026-03-14'] }
  const errors = await mockApi(page, state)
  const first = '/dashboard?period_start=2026-02-12&period_end=2026-03-14&source=bookmark#balance'
  await page.goto(first)
  await expect(page.locator('.period-selector-range')).toHaveText('12.02.2026 → 14.03.2026')
  await page.reload()
  await expect(page.locator('.period-selector-range')).toHaveText('12.02.2026 → 14.03.2026')
  state.period = ['2026-04-01', '2026-04-30']
  await page.goto('/dashboard?period_start=2026-04-01&period_end=2026-04-30')
  await expect(page.locator('.period-selector-range')).toHaveText('01.04.2026 → 30.04.2026')
  state.period = ['2026-02-12', '2026-03-14']
  await page.goBack()
  await expect(page.locator('.period-selector-range')).toHaveText('12.02.2026 → 14.03.2026')
  await page.locator('.period-selector-trigger').click()
  state.period = ['2026-10-01', '2026-10-31']
  await page.getByRole('button', { name: 'Current period', exact: true }).click()
  await expect(page).toHaveURL(/period_start=2026-10-01&period_end=2026-10-31&source=bookmark#balance$/)
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.locator('main h1')).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'Previous period', exact: true })).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`dashboard-period-${width}.png`), fullPage: true, animations: 'disabled' })
  }
  expect(errors).toEqual([])
})

test('legacy chart links resolve their meter before requesting data and survive tabs', async ({ page }) => {
  const state: ApiState = { populated: true, period: ['2026-02-12', '2026-03-14'], qualityPeriod: ['2026-02-12', '2026-03-14'] }
  const errors = await mockApi(page, state)
  await page.goto('/metering/chart?from=2026-02-12&to=2026-03-14&metering_point=mp42&quality_severity=red#readings')
  const meter = page.getByRole('combobox', { name: 'Metering Point *', exact: true })
  await expect(meter).toHaveValue('mp42')
  await expect(page.locator('.period-selector-range')).toHaveText('12.02.2026 → 14.03.2026')
  await page.getByRole('tab', { name: 'Data Quality', exact: true }).click()
  await expect(page).toHaveURL(/\/metering\/quality\?from=2026-02-12&to=2026-03-14&metering_point=mp42&quality_severity=red#readings$/)
  await page.getByRole('tab', { name: 'Charts', exact: true }).click()
  await expect(meter).toHaveValue('mp42')
  await page.locator('.period-selector-trigger').click()
  state.period = ['2026-10-01', '2026-10-31']
  await page.getByRole('button', { name: 'Current period', exact: true }).click()
  const url = new URL(page.url())
  expect(url.searchParams.has('from')).toBe(false)
  expect(url.searchParams.has('to')).toBe(false)
  expect(url.searchParams.get('metering_point')).toBe('mp42')
  expect(url.searchParams.get('quality_severity')).toBe('red')
  expect(url.hash).toBe('#readings')
  await page.reload()
  await expect(meter).toHaveValue('mp42')
  expect(errors).toEqual([])
})

test('invoices await interval data and keep historical periods below the aligned floor', async ({ page }, testInfo) => {
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const state: ApiState = {
    endpoint: '/zev/zevs/', pending, interval: 'quarterly', communityStart: '2026-02-15',
    invoicePeriod: ['2026-02-15', '2026-02-28'], populated: true,
  }
  const errors = await mockApi(page, state)
  const overviewCalls: string[] = []
  page.on('request', request => {
    if (request.url().includes('/period-overview/')) overviewCalls.push(request.url())
  })
  await page.goto('/billing/invoices?period_start=2026-02-15&period_end=2026-02-28&source=history#invoices')
  await expect(page.locator('main h1')).toHaveCount(1)
  await expect(page.locator('.skeleton-block').first()).toBeVisible()
  expect(overviewCalls).toEqual([])
  release()
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await expect(page.locator('.period-selector-range')).toHaveText('15.02.2026 → 28.02.2026')
  await expect(page.getByRole('button', { name: 'Previous period', exact: true })).toBeDisabled()
  await page.getByRole('tab', { name: 'Emails', exact: true }).click()
  expect(new URL(page.url()).hash).toBe('#invoices')
  await page.getByRole('tab', { name: 'Invoices', exact: true }).click()
  await expect(page.locator('.period-selector-range')).toHaveText('15.02.2026 → 28.02.2026')
  await expect(page.locator('main h1')).toHaveCount(1)
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.locator('tbody tr')).toHaveCount(1)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`billing-historical-${width}.png`), fullPage: true, animations: 'disabled' })
  }
  expect(errors).toEqual([])
})

test('scope switches clear invalid meters and participants before their next request', async ({ page }) => {
  const range: [string, string] = ['2026-02-12', '2026-03-14']
  const state: ApiState = { populated: true, period: range, preferred: '42', zevs: [
    { id: '42', name: 'Review ZEV' }, { id: '43', name: 'Other ZEV' },
  ] }
  const errors = await mockApi(page, state)
  await page.goto('/metering/chart?period_start=2026-02-12&period_end=2026-03-14&metering_point=mp42#readings')
  const meter = page.getByRole('combobox', { name: 'Metering Point *', exact: true })
  await expect(meter).toHaveValue('mp42')
  await page.locator('main .community-switch').click()
  state.expectedScope = '43'
  await page.getByRole('menuitem', { name: 'Other ZEV' }).click()
  await expect(page.locator('main .eyebrow').first()).toHaveText('Other ZEV')
  // The unavailable meter is cleared; the chart falls back to the new community's total.
  await expect.poll(() => new URL(page.url()).searchParams.has('metering_point')).toBe(false)
  await expect(meter).toHaveValue('__zev_total__')
  await expect(page.locator('.period-selector-range')).toHaveText('12.02.2026 → 14.03.2026')
  expect(new URL(page.url()).hash).toBe('#readings')

  state.preferred = '42'
  state.expectedScope = '42'
  await page.goto('/dashboard?period_start=2026-02-12&period_end=2026-03-14#balance')
  const participant = page.getByRole('combobox', { name: 'Participant', exact: true })
  await participant.selectOption('p42')
  await expect(participant).toHaveValue('p42')
  await page.locator('main .community-switch').click()
  state.period = ['2026-10-01', '2026-10-31']
  state.expectedScope = '43'
  await page.getByRole('menuitem', { name: 'Other ZEV' }).click()
  await expect(participant).toHaveValue('')
  await expect(page.locator('.period-selector-range')).toHaveText('01.10.2026 → 31.10.2026')
  await expect(page.locator('main .eyebrow').first()).toHaveText('Other ZEV')
  expect(new URL(page.url()).hash).toBe('#balance')
  await page.waitForLoadState('networkidle')
  expect(errors).toEqual([])
})

test('unfiltered quality remains available when the independent meter list fails', async ({ page }) => {
  const state: ApiState = { endpoint: '/zev/metering-points/', failed: true, qualityEmpty: true }
  const errors = await mockApi(page, state)
  await page.goto('/metering/quality')
  await expect(page.locator('main .empty-state')).toBeVisible()
  const failure = page.locator('main .error-banner')
  await expect(failure).toBeVisible({ timeout: 20_000 })
  state.failed = false
  await failure.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(failure).toHaveCount(0)
  await expect(page.locator('main .empty-state')).toBeVisible()
  expect(errors).toEqual([])
})

test('a deep-linked meter shows loading, not a false empty state, while the list resolves', async ({ page }) => {
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const state: ApiState = { populated: true, endpoint: '/zev/metering-points/', pending }
  const errors = await mockApi(page, state)
  await page.goto('/metering/chart?period_start=2026-10-01&period_end=2026-10-31&metering_point=mp42')
  await expect(page.locator('main .skeleton-block').first()).toBeVisible()
  await expect(page.getByText('No metering point selected', { exact: true })).toHaveCount(0)
  release()
  const meter = page.getByRole('combobox', { name: 'Metering Point *', exact: true })
  await expect(meter).toHaveValue('mp42')
  await expect(page.getByText('No readings in this period', { exact: true })).toBeVisible()
  await expect(page.getByText('No metering point selected', { exact: true })).toHaveCount(0)
  expect(errors).toEqual([])
})

test('the whole-community total loads without the meter inventory', async ({ page }) => {
  const state: ApiState = { populated: true, endpoint: '/zev/metering-points/', failed: true }
  const errors = await mockApi(page, state)
  await page.goto('/metering/chart?period_start=2026-10-01&period_end=2026-10-31&metering_point=__zev_total__')
  const meter = page.getByRole('combobox', { name: 'Metering Point *', exact: true })
  await expect(meter).toHaveValue('__zev_total__')
  await expect(page.locator('main .error-banner')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('No metering point selected', { exact: true })).toHaveCount(0)
  await expect(page.getByText('No readings in this period', { exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('the meter-list retry disables while a cached list refetches', async ({ page }) => {
  const state: ApiState = { populated: true }
  const errors = await mockApi(page, state)
  await page.goto('/metering/chart?period_start=2026-10-01&period_end=2026-10-31')
  const meter = page.getByRole('combobox', { name: 'Metering Point *', exact: true })
  // Whole-community total (the management default) and the one meter; no empty placeholder.
  await expect(meter.locator('option')).toHaveCount(2)
  await expect(meter).toHaveValue('__zev_total__')
  state.endpoint = '/zev/metering-points/'
  state.failed = true
  await page.evaluate(() => {
    for (const value of ['hidden', 'visible']) {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value })
      window.dispatchEvent(new Event('visibilitychange'))
    }
  })
  const warning = page.locator('main .warning-banner')
  await expect(warning).toBeVisible({ timeout: 20_000 })
  let release!: () => void
  state.pending = new Promise<void>(resolve => { release = resolve })
  state.failed = false
  await warning.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(warning.getByRole('button', { name: 'Loading...', exact: true })).toBeDisabled()
  release()
  await expect(warning).toHaveCount(0)
  expect(errors).toEqual([])
})

test('a quality row jumps to its meter chart with consistent identities', async ({ page }) => {
  const state: ApiState = { populated: true, period: ['2026-10-01', '2026-10-31'], qualityPeriod: ['2026-10-01', '2026-10-31'] }
  const errors = await mockApi(page, state)
  await page.goto('/metering/quality?period_start=2026-10-01&period_end=2026-10-31')
  await page.getByRole('button', { name: 'MP-42', exact: true }).click()
  await expect(page).toHaveURL(/\/metering\/chart\?.*metering_point=mp42/)
  const meter = page.getByRole('combobox', { name: 'Metering Point *', exact: true })
  await expect(meter).toHaveValue('mp42')
  await expect(page.getByText('No readings in this period', { exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('an invoice deletion dialog does not survive a community switch', async ({ page }) => {
  const state: ApiState = {
    populated: true,
    preferred: '42',
    zevs: [{ id: '42', name: 'Review ZEV' }, { id: '43', name: 'Other ZEV' }],
    invoicePeriod: ['2026-09-01', '2026-09-30'],
  }
  const errors = await mockApi(page, state)
  await page.goto('/billing/invoices?period_start=2026-09-01&period_end=2026-09-30')
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await page.getByRole('button', { name: 'More', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Delete invoice', exact: true }).click()
  await expect(page.getByText('Delete Invoice', { exact: true })).toBeVisible()
  // The modal overlay blocks the sidebar, so reconcile by removing the
  // selected community and refetching on focus — the dialog must not survive.
  state.transitionScope = '42'
  state.zevs = [{ id: '43', name: 'Other ZEV' }]
  const loaded = page.waitForResponse(response =>
    new URL(response.url()).pathname.endsWith('/invoices/invoices/period-overview/') &&
    response.status() === 200 &&
    new URL(response.url()).searchParams.get('zev_id') === '43', { timeout: 30_000 })
  await page.evaluate(() => {
    for (const value of ['hidden', 'visible']) {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value })
      window.dispatchEvent(new Event('visibilitychange'))
    }
  })
  await loaded
  await expect(page.locator('main .eyebrow').first()).toHaveText('Other ZEV')
  await expect(page.getByText('Delete Invoice', { exact: true })).toHaveCount(0)
  expect(errors).toEqual([])
})

test('my invoices show only the account\u2019s own participant rows', async ({ page }) => {
  const state: ApiState = {
    populated: true,
    preferred: '42',
    roleByZev: { '42': 'participant', '43': 'manager' },
    zevs: [
      { id: '42', name: 'Review ZEV' },
      { id: '43', name: 'Other ZEV' },
    ],
    invoices: [
      { id: '1', invoice_number: 'R-1', zev: '42', zev_name: 'Review ZEV', participant: 'p42', participant_name: 'Participant A', status: 'sent', total_chf: '10.00', pdf_url: null },
      { id: '2', invoice_number: 'R-9', zev: '43', zev_name: 'Other ZEV', participant: 'p43-other', participant_name: 'Somebody Else', status: 'sent', total_chf: '99.00', pdf_url: null },
    ],
  }
  const errors = await mockApi(page, state)
  await page.goto('/me/invoices')
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await expect(page.locator('tbody')).toContainText('R-1')
  await expect(page.locator('tbody')).not.toContainText('R-9')
  await page.waitForLoadState('networkidle')
  expect(errors).toEqual([])
})


for (const [path, button, title] of [
  ['/participants', 'New Participant', 'Create Participant'],
  ['/tariffs', 'New Tariff', 'Create Tariff'],
]) {
  test(`writable community reconciliation closes ${path} drafts`, async ({ page }, testInfo) => {
    const state: ApiState = {
      role: 'manager', populated: true, preferred: '42',
      zevs: [{ id: '42', name: 'Review ZEV' }, { id: '43', name: 'Other ZEV' }],
    }
    const errors = await mockApi(page, state)
    await page.goto(path)
    await page.getByRole('button', { name: button, exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText(title)
    state.transitionScope = '42'
    state.zevs = [{ id: '43', name: 'Other ZEV' }]
    await page.evaluate(() => {
      for (const value of ['hidden', 'visible']) {
        Object.defineProperty(document, 'visibilityState', { configurable: true, value })
        window.dispatchEvent(new Event('visibilitychange'))
      }
    })
    await expect(page.locator('main .eyebrow').first()).toHaveText('Other ZEV')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByRole('button', { name: button, exact: true })).toBeEnabled()
    for (const width of [1440, 400]) {
      await page.setViewportSize({ width, height: 900 })
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`scope-reset-${width}.png`), fullPage: true })
    }
    expect(errors).toEqual([])
  })
}

test('participant edit intent waits for the community record before consuming its URL', async ({ page }) => {
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const errors = await mockApi(page, { role: 'manager', populated: true, endpoint: '/zev/zevs/', pending })
  await page.goto('/participants?focus=p42&field=valid_to')
  await expect(page).toHaveURL(/focus=p42&field=valid_to/)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  release()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page).not.toHaveURL(/focus=/)
  expect(errors).toEqual([])
})


test('whole-community links survive a cold community lookup and request the aggregate', async ({ page }) => {
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const errors = await mockApi(page, { populated: true, endpoint: '/zev/zevs/', pending })
  const chartRequests: string[] = []
  page.on('request', request => {
    if (request.url().includes('/chart-data/')) chartRequests.push(request.url())
  })
  await page.goto('/metering/chart?metering_point=__zev_total__')
  await expect(page.locator('main h1')).toHaveCount(1)
  await expect(page).toHaveURL(/metering_point=__zev_total__/)
  expect(chartRequests).toEqual([])
  release()
  await expect(page.getByRole('combobox', { name: 'Metering Point *', exact: true })).toHaveValue('__zev_total__')
  await expect.poll(() => chartRequests.length).toBeGreaterThan(0)
  expect(chartRequests.every(url => new URL(url).searchParams.get('zev_id') === '42'
    && !new URL(url).searchParams.has('metering_point'))).toBe(true)
  await expect(page).toHaveURL(/metering_point=__zev_total__/)
  expect(errors).toEqual([])
})

test('failed initial community lookup preserves the whole-community link until retry succeeds', async ({ page }) => {
  const state: ApiState = { populated: true, scopeFailed: true }
  const errors = await mockApi(page, state)
  await page.goto('/metering/chart?metering_point=__zev_total__')
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
  await expect(page).toHaveURL(/metering_point=__zev_total__/)
  state.scopeFailed = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Metering Point *', exact: true })).toHaveValue('__zev_total__')
  expect(errors).toEqual([])
})


for (const [label, state] of [
  ['participant scope', { role: 'participant' as const, populated: true }],
  ['participant scope with an unrelated failed management lookup', {
    roleByZev: { '42': 'manager' as const, '43': 'participant' as const }, preferred: '43', populated: true, scopeFailed: true,
    zevs: [{ id: '42', name: 'Review ZEV' }, { id: '43', name: 'Other ZEV' }],
  }],
  ['no community', { scopeEmpty: true }],
] as const) {
  test(`whole-community selection clears after confirmed ${label}`, async ({ page }) => {
    const errors = await mockApi(page, state)
    await page.goto('/metering/chart?metering_point=__zev_total__')
    await expect(page.locator('main h1')).toHaveCount(1)
    await expect(page).not.toHaveURL(/metering_point=/)
    expect(errors).toEqual([])
  })
}

for (const [path, endpoint, body] of [
  ['/participants', '/zev/participants/', '.participant-toolbar'],
  ['/tariffs', '/tariffs/tariffs/series/', '.tariff-toolbar'],
] as const) {
  test(`${path} waits for resolved scope through loading, failure and empty results`, async ({ page }) => {
    let release!: () => void
    const state: ApiState = { populated: true, scopeFailed: true, endpoint: '/zev/zevs/', pending: new Promise<void>(resolve => { release = resolve }) }
    const errors = await mockApi(page, state)
    const requests: string[] = []
    page.on('request', request => {
      if (new URL(request.url()).pathname.endsWith(endpoint)) requests.push(request.url())
    })
    await page.goto(path)
    await expect(page.locator('main h1')).toHaveCount(1)
    await expect(page.locator('main .skeleton-block').first()).toBeVisible()
    await expect(page.locator(body)).toHaveCount(0)
    expect(requests).toEqual([])
    release()
    const failure = page.locator('main .error-banner')
    await expect(failure).toBeVisible({ timeout: 20_000 })
    await expect(page.locator(body)).toHaveCount(0)
    expect(requests).toEqual([])
    state.scopeFailed = false
    state.scopeEmpty = true
    await failure.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(page.locator('main .empty-state')).toBeVisible()
    await expect(page.locator('main .empty-state a')).toHaveAttribute('href', '/admin/zevs')
    await expect(page.locator(body)).toHaveCount(0)
    expect(requests).toEqual([])
    state.scopeEmpty = false
    await page.reload()
    await expect(page.locator(body)).toBeVisible()
    expect(requests.length).toBeGreaterThan(0)
    if (path === '/tariffs') expect(requests.every(url => new URL(url).searchParams.get('zev_id') === '42')).toBe(true)
    expect(errors).toEqual([])
  })

  test(`${path} retains its draft after a failed refresh of usable scope`, async ({ page }, testInfo) => {
    const state: ApiState = { populated: true }
    const errors = await mockApi(page, state)
    await page.goto(path)
    await expect(page.locator(body)).toBeVisible()
    await page.getByRole('button', { name: path === '/participants' ? 'New Participant' : 'New Tariff', exact: true }).click()
    const draft = page.getByRole('dialog')
    const name = draft.getByRole('textbox').first()
    await name.fill('Retained draft')
    state.scopeFailed = true
    await page.evaluate(() => {
      for (const value of ['hidden', 'visible']) {
        Object.defineProperty(document, 'visibilityState', { configurable: true, value })
        window.dispatchEvent(new Event('visibilitychange'))
      }
    })
    await expect(page.locator('main .warning-banner')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator(body)).toBeVisible()
    await expect(name).toHaveValue('Retained draft')
    for (const width of [1440, 400]) {
      await page.setViewportSize({ width, height: 900 })
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`scope-refresh-${width}.png`), fullPage: true })
    }
    expect(errors).toEqual([])
  })
}
