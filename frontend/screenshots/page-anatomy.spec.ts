import { expect, test, type Page } from '@playwright/test'
import { apiErrors, mockApi, type ApiState } from './page-anatomy-fixtures'

test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })

test.afterEach(async ({ page }, testInfo) => {
  const errors = apiErrors.get(page) ?? []
  if (errors.length) await testInfo.attach('browser-errors', { body: JSON.stringify(errors), contentType: 'application/json' })
  expect(errors).toEqual([])
})

const healthPeriod: [string, string] = ['2026-09-02', '2026-10-02']

async function refetchOnFocus(page: Page) {
  await page.evaluate(() => {
    for (const value of ['hidden', 'visible']) {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value })
      window.dispatchEvent(new Event('visibilitychange'))
    }
  })
}

async function expectTitle(page: Page) {
  await expect(page.locator('main h1')).toHaveCount(1)
  await expect(page.locator('main h1')).toBeVisible()
}

function successfulResponse(page: Page, endpoint: string, scope?: string) {
  return page.waitForResponse(response => new URL(response.url()).pathname.endsWith(endpoint) && response.status() === 200 &&
    (!scope || new URL(response.url()).searchParams.get('zev_id') === scope), { timeout: 30_000 })
}

test('participant KPI grid has spacing and columns at desktop and mobile widths', async ({ page }, testInfo) => {
  await mockApi(page, { role: 'participant' })
  await page.goto('/dashboard')
  const grid = page.locator('main .stat-grid--wide')
  await expect(grid.locator('.stat-card')).toHaveCount(4)
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 })
    if (width === 400) {
      await expect.poll(() => page.locator('aside').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
    }
    await expect(grid).toHaveCSS('display', 'grid')
    await expect(grid).toHaveCSS('gap', '16px')
    await expectTitle(page)
    const geometry = await grid.evaluate(element => {
      const rects = Array.from(element.children, child => child.getBoundingClientRect())
      return {
        columns: getComputedStyle(element).gridTemplateColumns.split(' ').length,
        overflow: document.documentElement.scrollWidth > innerWidth,
        horizontalGap: rects[1].left - rects[0].right,
        verticalGap: rects[1].top - rects[0].bottom,
      }
    })
    expect(geometry.overflow).toBe(false)
    if (width === 1440) {
      expect(geometry.columns).toBeGreaterThan(1)
      expect(geometry.horizontalGap).toBeCloseTo(16)
    } else {
      expect(geometry.columns).toBe(1)
      expect(geometry.verticalGap).toBeCloseTo(16)
    }
    await page.screenshot({ path: testInfo.outputPath(`participant-${width}.png`), fullPage: true })
  }

})

test('failed scope refetch keeps report controls and their state, then retries', async ({ page }) => {
  const state: ApiState = {}
  await mockApi(page, state)
  const initial = successfulResponse(page, '/annual-report/')
  await page.goto('/reports')
  await initial
  const year = page.getByRole('combobox', { name: 'Year', exact: true })
  await expect(year).toBeVisible()
  const selectedYear = '2024'
  state.year = Number(selectedYear)
  const report = successfulResponse(page, '/annual-report/')
  await year.selectOption(selectedYear)
  await report
  const original = await year.elementHandle()
  state.scopeFailed = true
  await refetchOnFocus(page)
  const warning = page.locator('main .warning-banner')
  await expect(warning).toBeVisible({ timeout: 20_000 })
  await expect(year).toHaveValue(selectedYear)
  expect(await year.evaluate((node, original) => node === original, original)).toBe(true)
  await expectTitle(page)
  state.scopeFailed = false
  await warning.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(warning).toHaveCount(0)
  await expect(year).toHaveValue(selectedYear)

})

test('scope loading, initial failure and confirmed empty results keep the settings title', async ({ page }) => {
  let release!: () => void
  const state: ApiState = { endpoint: '/zev/zevs/', pending: new Promise<void>(resolve => { release = resolve }) }
  await mockApi(page, state)
  await page.goto('/zev-settings/general')
  await expect(page.locator('main .skeleton-block').first()).toBeVisible()
  await expectTitle(page)
  state.scopeFailed = true
  state.pending = undefined
  release()
  const failure = page.locator('main .error-banner')
  await expect(failure).toBeVisible({ timeout: 20_000 })
  await expectTitle(page)
  state.scopeFailed = false
  state.scopeEmpty = true
  await failure.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.locator('main .empty-state')).toBeVisible()
  await expectTitle(page)
  await expect(page.locator('main .empty-state a')).toHaveAttribute('href', '/admin/zevs')
  await page.goto('/dashboard')
  await expect(page.locator('main .empty-state')).toBeVisible()
  await expectTitle(page)
  await expect(page.locator('main select')).toHaveCount(0)
  state.scopeEmpty = false
  await page.goto('/zev-settings/general')
  await expect(page.getByRole('tab', { name: 'General', exact: true })).toBeVisible()
  await expectTitle(page)

})

for (const [path, endpoint, body] of [
  ['/participants', '/zev/participants/', '.participant-toolbar'],
  ['/tariffs', '/tariffs/tariffs/series/', '.tariff-toolbar'],
  ['/metering/imports', '/metering/import-logs/', '.empty-state'],
  ['/admin/accounts/users', '/auth/users/', 'table'],
  ['/admin/zevs', '/zev/zevs/', 'table'],
  ['/billing/invoices', '/invoices/invoices/period-overview/', '.empty-state'],
  ['/billing/invoices/1', '/invoices/invoices/1/', '.badge-sent'],
]) {
  test(`${path} keeps one title across loading, error and content states`, async ({ page }) => {
    let release!: () => void
    const state: ApiState = { endpoint, pending: new Promise<void>(resolve => { release = resolve }) }
    await mockApi(page, state)
    await page.goto(path)
    await expect(page.locator('main .skeleton-block').first()).toBeVisible()
    await expectTitle(page)
    state.failed = true
    state.pending = undefined
    release()
    await expect(page.locator('main [role="alert"]').first()).toBeVisible({ timeout: 20_000 })
    await expectTitle(page)
    state.failed = false
    const succeeded = successfulResponse(page, endpoint)
    const retry = page.locator('main [role="alert"]').getByRole('button', { name: 'Retry', exact: true })
    await expect(retry).toBeVisible()
    await retry.click()
    await succeeded
    await expect(page.locator(`main ${body}`).first()).toBeVisible()
    await expectTitle(page)

  })
}

test('severity toggles support Tab, Enter and Space', async ({ page }) => {
  await mockApi(page)
  await page.goto('/metering/quality')
  const meter = page.getByRole('cell', { name: 'MP-1', exact: true })
  await expect(meter).toBeVisible()
  const toggles = page.locator('main .stat-card--interactive')
  await expect(toggles).toHaveCount(3)
  await toggles.first().focus()
  await page.keyboard.press('Tab')
  await expect(toggles.nth(1)).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(toggles.nth(1)).toHaveAttribute('aria-pressed', 'true')
  await expect(meter).toHaveCount(0)
  await page.keyboard.press('Space')
  await expect(toggles.nth(1)).toHaveAttribute('aria-pressed', 'false')
  await expect(meter).toBeVisible()
  await expectTitle(page)

})

test('viewer metering toolbar has no empty action cluster', async ({ page }) => {
  await mockApi(page, { role: 'viewer', qualityPeriod: healthPeriod })
  await page.goto('/metering/points')
  await expect(page.locator('main .metering-toolbar')).toBeVisible()
  await expect(page.locator('main .metering-toolbar .toolbar-actions')).toHaveCount(0)
  await expectTitle(page)

})

for (const invoiceState of ['loading', 'error']) {
  test(`billing email scope warning survives invoice ${invoiceState}`, async ({ page }) => {
    let release!: () => void
    const state: ApiState = { endpoint: '/invoices/invoices/', pending: new Promise<void>(resolve => { release = resolve }) }
    await mockApi(page, state)
    await page.goto('/billing/emails')
    await expect(page.locator('main .skeleton-block').first()).toBeVisible()
    state.scopeFailed = true
    await refetchOnFocus(page)
    const warning = page.locator('main .warning-banner')
    await expect(warning).toBeVisible({ timeout: 20_000 })
    if (invoiceState === 'error') {
      state.failed = true
      state.pending = undefined
      release()
      await expect(page.locator('main .error-banner')).toBeVisible({ timeout: 20_000 })
    } else {
      await expect(page.locator('main .skeleton-block').first()).toBeVisible()
    }
    await expect(warning.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
    await expectTitle(page)
    state.scopeFailed = false
    await warning.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(warning).toHaveCount(0)
    if (invoiceState === 'loading') {
      const loaded = successfulResponse(page, '/invoices/invoices/')
      state.pending = undefined
      release()
      await loaded
      await expect(page.locator('main .billing-workflow-table tbody .muted')).toBeVisible()
    } else {
      await expect(page.locator('main .error-banner')).toBeVisible()
      state.failed = false
      const loaded = successfulResponse(page, '/invoices/invoices/')
      await page.locator('main .error-banner').getByRole('button', { name: 'Retry', exact: true }).click()
      await loaded
      await expect(page.locator('main .billing-workflow-table tbody .muted')).toBeVisible()
    }

  })
}

test('settings draft survives a scope failure; successful scope removal shows empty state', async ({ page }) => {
  const state: ApiState = {}
  await mockApi(page, state)
  await page.goto('/zev-settings/general')
  const name = page.getByRole('textbox', { name: 'Name', exact: true })
  await name.fill('Unsaved name')
  state.scopeFailed = true
  await refetchOnFocus(page)
  const warning = page.locator('main .warning-banner')
  await expect(warning).toBeVisible({ timeout: 20_000 })
  await expect(name).toHaveValue('Unsaved name')
  state.scopeFailed = false
  state.scopeEmpty = true
  await warning.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.locator('main .empty-state')).toBeVisible()
  await expect(name).toHaveCount(0)
  await expectTitle(page)

})

test('metering refresh failure preserves an open draft and retry recovers', async ({ page }) => {
  const state: ApiState = { endpoint: '/zev/metering-points/', qualityPeriod: healthPeriod }
  await mockApi(page, state)
  await page.goto('/metering/points')
  await page.locator('main .metering-toolbar .toolbar-actions button').click()
  const dialog = page.getByRole('dialog')
  const meterId = dialog.getByRole('textbox', { name: 'Meter ID *', exact: true })
  await meterId.fill('Unsaved meter')
  state.failed = true
  await refetchOnFocus(page)
  const warning = page.locator('main .warning-banner')
  await expect(warning).toBeVisible({ timeout: 20_000 })
  await expect(dialog).toBeVisible()
  await expect(meterId).toHaveValue('Unsaved meter')
  state.failed = false
  // The modal deliberately makes background controls inert.
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await warning.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(warning).toHaveCount(0)
  await expectTitle(page)

})

test('quality empty state gives viewers neutral guidance and metering navigation', async ({ page }) => {
  const state: ApiState = { role: 'viewer', qualityEmpty: true }
  await mockApi(page, state)
  await page.goto('/metering/quality')
  const action = page.locator('main .empty-state').getByRole('link', { name: 'Metering Points', exact: true })
  await expect(page.locator('main .empty-state')).toContainText('No metering points for this selection')
  await expect(page.locator('main .empty-state')).not.toContainText('Add metering points')
  await expect(action).toHaveAttribute('href', '/metering/points')
  state.qualityPeriod = healthPeriod
  await action.click()
  await expect(page.locator('main .metering-toolbar')).toBeVisible()

})

test('admin dashboard renders manager summary cards', async ({ page }) => {
  await mockApi(page)
  await page.goto('/dashboard')
  await expect(page.locator('main .kpi-row .stat-card')).toHaveCount(5)
  await expect(page.locator('main .kpi-row .stat-card--accent')).toHaveCount(1)
  await expectTitle(page)

})

for (const role of ['admin', 'manager'] as const) {
  test(`${role} quality route without a community does not leave a blank panel`, async ({ page }, testInfo) => {
    await mockApi(page, { role, scopeEmpty: true })
    const loaded = successfulResponse(page, '/auth/me/')
    await page.goto('/metering/quality')
    await loaded
    await expect(page.locator('main .empty-state')).toBeVisible()
    if (role === 'admin') {
      await expectTitle(page)
      await expect(page.locator('main [role="tabpanel"]')).toHaveCount(0)
      await expect(page).toHaveURL(/\/metering\/quality$/)
    } else {
      await expect(page).toHaveURL(/\/$/)
      await expect(page.locator('main .empty-state a')).toHaveAttribute('href', '/account')
      await expect(page.locator('main h1')).toHaveCount(0)
    }
    await page.screenshot({ path: testInfo.outputPath(`${role}-no-community.png`), fullPage: true })

  })
}

for (const path of ['/', '/dashboard', '/metering/chart', '/metering/points']) {
  test(`former participant opening ${path} reaches only their invoices`, async ({ page }) => {
    await mockApi(page, { role: 'former', populated: true })
    await page.goto(path)
    await expect(page).toHaveURL(/\/me\/invoices$/)
    await expect(page.locator('main').getByText('R-1', { exact: true })).toBeVisible()
    await expectTitle(page)
    await expect(page.locator('main .stat-card, main .metering-toolbar')).toHaveCount(0)

  })
}

test('long German headers and narrow tile containers fit at desktop and mobile widths', async ({ page }, testInfo) => {
  await mockApi(page)
  await page.goto('/zev-settings/general')
  await expect(page.getByRole('textbox', { name: 'Name', exact: true })).toBeVisible()
  await page.evaluate(async fixturePath => {
    const { mountPageLayout } = await import(/* @vite-ignore */ fixturePath)
    mountPageLayout()
  }, '/screenshots/fixtures/page-layout.tsx')
  const fixture = page.locator('#page-layout-fixture')
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(fixture.locator('.page-header-text')).toHaveCSS('min-width', '0px')
    await expect(fixture.locator('h1')).toHaveCSS('font-weight', '650')
    for (const selector of ['.page-header', '.page-header-actions', '.toolbar', '.toolbar-actions', '.stat-grid']) {
      const overflow = await fixture.locator(selector).evaluate(element => element.scrollWidth - element.clientWidth)
      expect(overflow, `${selector} overflow at ${width}px`).toBeLessThanOrEqual(1)
    }
    await fixture.screenshot({ path: testInfo.outputPath(`long-header-${width}.png`) })
  }

})

for (const [path, endpoint, text] of [
  ['/participants', '/zev/participants/', 'Participant A'],
  ['/tariffs', '/tariffs/tariffs/series/', 'Tariff 42'],
  ['/admin/accounts/users', '/auth/users/', 'account@example.test · account@example.test'],
  ['/billing/invoices', '/invoices/invoices/period-overview/', 'Participant A'],
  ['/metering/points', '/zev/metering-points/', 'MP-42'],
]) {
  test(`${path} renders populated content at narrow widths`, async ({ page }, testInfo) => {
    await mockApi(page, { populated: true, qualityPeriod: path === '/metering/points' ? healthPeriod : undefined })
    const loaded = successfulResponse(page, endpoint)
    await page.goto(path)
    await loaded
    await expect(page.locator('main').getByText(text, { exact: true }).first()).toBeVisible()
    await expectTitle(page)
    await page.setViewportSize({ width: 400, height: 900 })
    await expect.poll(() => page.locator('aside').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
    await expect.poll(() => page.locator('main .page-header, main .card, main .table-card').evaluateAll(elements =>
      elements.filter(element => element.getBoundingClientRect().right > innerWidth + 1).map(element => element.className),
    )).toEqual([])
    await page.screenshot({ path: testInfo.outputPath('populated-400.png'), fullPage: true })

  })
}

const twoZevs = [{ id: '42', name: 'Review ZEV' }, { id: '43', name: 'Other ZEV' }]
const overviewEndpoint = '/invoices/invoices/period-overview/'

async function switchToOtherZev(page: Page) {
  await page.locator('.sidebar-zev-menu .user-menu-trigger').click()
  await page.locator('.zev-dropdown-item').filter({ hasText: 'Other ZEV' }).click()
}

test('switching communities ignores a late response from the previous selection', async ({ page }) => {
  const state: ApiState = { zevs: twoZevs, populated: true, endpoint: overviewEndpoint }
  await mockApi(page, state)
  await page.goto('/billing/invoices')
  await expect(page.getByRole('cell', { name: 'Participant A', exact: true })).toBeVisible()
  let release!: () => void
  state.pendingScope = '42'
  state.pending = new Promise<void>(resolve => { release = resolve })
  const oldRequest = new Promise<void>(resolve => { state.onPending = resolve })
  await refetchOnFocus(page)
  await oldRequest
  const newResponse = successfulResponse(page, overviewEndpoint, '43')
  // Selection is optimistic; its requests can precede the preference PATCH.
  state.expectedScope = '43'
  await switchToOtherZev(page)
  await newResponse
  await expect(page.getByRole('cell', { name: 'Participant B', exact: true })).toBeVisible()
  const oldResponse = successfulResponse(page, overviewEndpoint, '42')
  state.pending = undefined
  release()
  await oldResponse
  await expect(page.getByRole('cell', { name: 'Participant B', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Participant A', exact: true })).toHaveCount(0)
  await expect(page.locator('main .eyebrow').first()).toHaveText('Other ZEV')

})

test('removing the selected community reconciles to the remaining community', async ({ page }) => {
  const state: ApiState = { zevs: twoZevs, populated: true, preferred: '42' }
  await mockApi(page, state)
  await page.goto('/billing/invoices')
  await expect(page.getByRole('cell', { name: 'Participant A', exact: true })).toBeVisible()
  state.transitionScope = '42'
  state.zevs = [twoZevs[1]]
  const loaded = successfulResponse(page, overviewEndpoint, '43')
  await refetchOnFocus(page)
  await loaded
  await expect(page.getByRole('cell', { name: 'Participant B', exact: true })).toBeVisible()
  await expect(page.locator('main .eyebrow').first()).toHaveText('Other ZEV')
  await expect(page.getByRole('cell', { name: 'Participant A', exact: true })).toHaveCount(0)
  state.transitionScope = undefined
  const refresh = successfulResponse(page, overviewEndpoint, '43')
  await refetchOnFocus(page)
  await refresh

})

for (const role of ['manager', 'viewer'] as const) {
  test(`${role} provider limits selection to granted communities and respects write access`, async ({ page }) => {
    await mockApi(page, { role, zevs: twoZevs, membershipIds: ['42'], populated: true, qualityPeriod: healthPeriod })
    await page.goto('/metering/points')
    await expect(page.locator('main .eyebrow').first()).toHaveText('Review ZEV')
    await expect(page.locator('main').getByText('MP-42', { exact: true }).first()).toBeVisible()
    await expect(page.locator('main').getByText('MP-43', { exact: true })).toHaveCount(0)
    await expect(page.locator('.sidebar-zev-menu')).toHaveCount(0)
    await expect(page.locator('main .metering-toolbar .toolbar-actions button')).toHaveCount(role === 'manager' ? 1 : 0)

  })
}

test('an account without a community receives guidance and recovers after access is granted', async ({ page }) => {
  const state: ApiState = { role: 'none' }
  await mockApi(page, state)
  await page.goto('/')
  await expect(page.locator('main .empty-state')).toBeVisible()
  await expect(page.locator('main .empty-state a')).toHaveAttribute('href', '/account')
  state.role = 'manager'
  const loaded = successfulResponse(page, '/invoices/invoices/readiness/')
  await page.reload()
  await loaded
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible()
  await expect(page.locator('main .eyebrow').first()).toHaveText('Review ZEV')

})

test('scope refresh failures retain email editor local state and its DOM node', async ({ page }) => {
  const state: ApiState = {}
  await mockApi(page, state)
  await page.goto('/zev-settings/documents')
  const toggle = page.locator('.zev-email-fields-toggle button')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  const original = await toggle.elementHandle()
  state.scopeFailed = true
  await refetchOnFocus(page)
  const warning = page.locator('main .warning-banner')
  await expect(warning).toBeVisible({ timeout: 20_000 })
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(await toggle.evaluate((node, original) => node === original, original)).toBe(true)
  state.scopeFailed = false
  await warning.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(warning).toHaveCount(0)
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')

})

async function openMeterDraft(page: Page, mode: 'create' | 'edit') {
  if (mode === 'create') await page.locator('main .metering-toolbar .toolbar-actions button').click()
  else {
    await page.locator('main').getByRole('button', { name: 'More', exact: true }).first().click()
    await page.getByRole('menuitem', { name: 'Edit', exact: true }).click()
  }
  await page.getByRole('dialog').getByRole('textbox', { name: 'Meter ID *', exact: true }).fill('Unsaved meter')
}

for (const mode of ['create', 'edit'] as const) {
  test(`${mode} meter draft closes after a non-admin membership is removed`, async ({ page }) => {
    const state: ApiState = { role: 'manager', zevs: twoZevs, preferred: '42', populated: true, qualityPeriod: healthPeriod }
    await mockApi(page, state)
    await page.goto('/metering/points')
    await expect(page.locator('main').getByText('MP-42', { exact: true }).first()).toBeVisible()
    await openMeterDraft(page, mode)
    state.transitionScope = '42'
    state.zevs = [twoZevs[1]]
    await refetchOnFocus(page)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.locator('main').getByText('MP-43', { exact: true }).first()).toBeVisible()
    state.transitionScope = undefined
    const refreshed = successfulResponse(page, '/zev/metering-points/', '43')
    await refetchOnFocus(page)
    await refreshed

  })

  test(`${mode} meter saves to its original community after a cached refresh failure`, async ({ page }) => {
    const state: ApiState = { endpoint: '/zev/metering-points/', populated: true, qualityPeriod: healthPeriod }
    await mockApi(page, state)
    let submitted!: (request: { method: string; path: string; payload: Record<string, unknown> }) => void
    const submission = new Promise<{ method: string; path: string; payload: Record<string, unknown> }>(resolve => { submitted = resolve })
    await page.route('**/api/v1/zev/metering-points/**', async route => {
      const request = route.request()
      if (request.method() === 'GET') return route.fallback()
      const payload = request.postDataJSON()
      submitted({ method: request.method(), path: new URL(request.url()).pathname, payload })
      await route.fulfill({ json: { id: 'mp42', ...payload } })
    })
    await page.goto('/metering/points')
    await expect(page.locator('main').getByText('MP-42', { exact: true }).first()).toBeVisible()
    await openMeterDraft(page, mode)
    state.failed = true
    await refetchOnFocus(page)
    await expect(page.locator('main .warning-banner')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole('dialog').getByRole('textbox', { name: 'Meter ID *', exact: true })).toHaveValue('Unsaved meter')
    state.failed = false
    const refreshed = successfulResponse(page, '/zev/metering-points/', '42')
    await page.getByRole('dialog').getByRole('button', { name: mode === 'edit' ? 'Save Changes' : 'Create Metering Point', exact: true }).click()
    const saved = await submission
    expect(saved.method).toBe(mode === 'edit' ? 'PATCH' : 'POST')
    expect(saved.path).toBe(`/api/v1/zev/metering-points/${mode === 'edit' ? 'mp42/' : ''}`)
    expect(saved.payload).toMatchObject({ zev: '42', meter_id: 'Unsaved meter' })
    await refreshed
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.locator('main .warning-banner')).toHaveCount(0)

  })
}

test('feasibility distinguishes loading, a failed flag check and confirmed disabled', async ({ page }) => {
  let release!: () => void
  const endpoint = '/feasibility/enabled/'
  const state: ApiState = { endpoint, pending: new Promise<void>(resolve => { release = resolve }) }
  await mockApi(page, state)
  await page.goto('/feasibility')
  await expect(page.locator('main .skeleton-block').first()).toBeVisible()
  state.failed = true
  state.pending = undefined
  release()
  const error = page.locator('main [role="alert"]')
  await expect(error).toBeVisible({ timeout: 20_000 })
  state.failed = false
  const loaded = successfulResponse(page, endpoint)
  await error.getByRole('button', { name: 'Retry', exact: true }).click()
  await loaded
  await expect(page.locator('main .card .muted')).toBeVisible()
  await expect(error).toHaveCount(0)
  await expectTitle(page)

})

test('meter inventory waits for management scope and offers recovery before querying', async ({ page }) => {
  const state: ApiState = { scopeFailed: true, populated: true, qualityPeriod: healthPeriod }
  await mockApi(page, state)
  const inventories: string[] = []
  page.on('request', request => {
    if (new URL(request.url()).pathname.endsWith('/zev/metering-points/')) inventories.push(request.url())
  })
  await page.goto('/metering/points')
  await expectTitle(page)
  await expect(page.locator('main [role="alert"]')).toBeVisible({ timeout: 20_000 })
  expect(inventories).toEqual([])
  state.scopeFailed = false
  state.scopeEmpty = true
  const empty = successfulResponse(page, '/zev/zevs/')
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await empty
  await expect(page.locator('main .empty-state')).toBeVisible()
  expect(inventories).toEqual([])
  state.scopeEmpty = false
  const populated = successfulResponse(page, '/zev/metering-points/', '42')
  await page.reload()
  await populated
  await expect(page.locator('main').getByText('MP-42', { exact: true }).first()).toBeVisible()
  await expectTitle(page)

})

test('disabling a manager community closes the assignment draft and leaves read-only meters', async ({ page }) => {
  const state: ApiState = { role: 'manager', populated: true, zevs: [twoZevs[0]], qualityPeriod: healthPeriod }
  await mockApi(page, state)
  await page.goto('/metering/points')
  await expect(page.locator('main').getByText('MP-42', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Assign participant', exact: true }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  state.zevs = [{ ...twoZevs[0], disabled_at: '2026-10-02T12:00:00Z' }]
  await refetchOnFocus(page)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('main').getByText('MP-42', { exact: true }).first()).toBeVisible()
  await expect(page.locator('main .metering-toolbar .toolbar-actions')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Assign participant', exact: true })).toHaveCount(0)

})

test('multi-community participants see their selected meter context and all-community invoice heading', async ({ page }) => {
  await mockApi(page, { role: 'participant', zevs: twoZevs, preferred: '43', populated: true, qualityPeriod: healthPeriod })
  const meters = successfulResponse(page, '/zev/metering-points/', '43')
  await page.goto('/metering/points')
  await meters
  await expect(page.locator('main .eyebrow').first()).toHaveText('Other ZEV')
  await expect(page.locator('main').getByText('MP-43', { exact: true }).first()).toBeVisible()
  await expect(page.locator('main').getByText('MP-42', { exact: true })).toHaveCount(0)
  await expect(page.locator('main .metering-toolbar .toolbar-actions')).toHaveCount(0)
  const summary = successfulResponse(page, '/dashboard-summary/', '43')
  await page.goto('/dashboard')
  await summary
  await expect(page.locator('main .eyebrow').first()).toHaveText('Other ZEV')
  await expect(page.getByRole('heading', { name: 'Invoices from all communities', exact: true })).toBeVisible()

})
