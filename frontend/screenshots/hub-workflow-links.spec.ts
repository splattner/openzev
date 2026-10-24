import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { mockApi, type ApiState } from './page-anatomy-fixtures'
import { DEFAULT_SECTIONS } from '../src/features/zev/transferSections'

const source = {
  id: 's1', label: 'Shared operator source', url: `https://prices.example.test/${'long-path/'.repeat(8)}`,
  api_version: 'v1_0_5', tariff_type: 'grid', tariff_name: 'Standard', enabled: false,
  last_fetch_status: 'failed', last_fetch_error: 'Operator unavailable', last_fetch_at: null,
  last_success_at: '2026-09-29T12:00:00Z', covers_from: '2026-09-01T00:00:00Z', covers_to: '2026-10-01T00:00:00Z',
  point_count: 12, linked_tariff_count: 7, linked_zev_count: 3, supports_backfill: true,
  empty_on_not_found: false, aggregated_tariff_types: [], created_at: '', updated_at: '',
}

async function sourceApi(page: Page, state?: ApiState) {
  await page.route('**/api/v1/tariffs/dynamic-sources/**', route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() !== 'GET') return route.fallback()
    if (path === '/api/v1/tariffs/dynamic-sources/') {
      return state?.failed ? route.fallback() : route.fulfill({ json: [source, { ...source, id: 's2', label: 'Other source' }] })
    }
    if (path === '/api/v1/tariffs/dynamic-sources/s1/prices/') {
      return route.fulfill({ json: {
        points: [], gaps: [], stats: { count: 0, min: null, max: null, average: null, negative_count: 0, gap_count: 0 },
      } })
    }
    return route.fallback()
  })
  await page.route('**/api/v1/tariffs/tariffs/series/**', route => {
    const request = route.request()
    if (request.method() !== 'GET' || new URL(request.url()).pathname !== '/api/v1/tariffs/tariffs/series/') return route.fallback()
    return route.fulfill({ json: [{
      zev: '42', name: 'Dynamic tariff', category: 'energy', billing_mode: 'energy', energy_type: 'grid',
      version_count: 1, active_version_id: 't1', gaps: [], versions: [{
        id: 't1', zev: '42', name: 'Dynamic tariff', category: 'energy', billing_mode: 'energy', energy_type: 'grid',
        valid_from: '2026-01-01', valid_to: null, fixed_price_chf: null, split_key: 'equal', notes: '', periods: [], dynamic_source: 's1',
      }],
    }] })
  })
}

async function auditApi(page: Page, populated = false, state?: ApiState) {
  const requests: URL[] = []
  const event = {
    id: 'e1', created_at: '2026-10-01T12:00:00Z', summary: 'Source fetched', zev: '42',
    action_category: 'tariff', action_type: 'source.fetch', target_type: 'tariffs.DynamicTariffSource',
    target_id: 's1', target_display: 'Shared operator source', status: 'success', actor_display: 'Admin',
    changes_json: {}, metadata_json: {}, source: 'api',
  }
  await page.route('**/api/v1/audit/events/**', route => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() !== 'GET') return route.fallback()
    if (url.pathname === '/api/v1/audit/events/filter-options/') {
      return route.fulfill({ json: { zevs: [{ id: '42', name: 'Review ZEV' }], actors: [] } })
    }
    if (populated && url.pathname === '/api/v1/audit/events/e1/') return route.fulfill({ json: event })
    if (url.pathname !== '/api/v1/audit/events/') return route.fallback()
    requests.push(url)
    if (state?.failed) return route.fallback()
    const hasEvents = populated && url.searchParams.get('target_id') !== 's2'
    const currentPage = Number(url.searchParams.get('page') ?? 1)
    return route.fulfill({ json: {
      results: hasEvents ? [event] : [], count: hasEvents ? 150 : 0,
      next: hasEvents && currentPage < 3 ? 'next' : null,
      previous: hasEvents && currentPage > 1 ? 'previous' : null,
    } })
  })
  return requests
}

async function navigateMounted(page: Page, url: string, replace = true) {
  await page.evaluate(({ url, replace }) => {
    history[replace ? 'replaceState' : 'pushState'](history.state, '', url)
    dispatchEvent(new PopStateEvent('popstate'))
  }, { url, replace })
}

async function refocusPage(page: Page) {
  await page.evaluate(() => {
    for (const value of ['hidden', 'visible']) {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value })
      window.dispatchEvent(new Event('visibilitychange'))
    }
  })
}

async function checkWidths(page: Page, name: string, outputPath: (name: string) => string) {
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.locator('main h1')).toHaveCount(1)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: outputPath(`${name}-${width}.png`), fullPage: true, animations: 'disabled' })
  }
}

test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })

for (const role of ['admin', 'manager', 'viewer'] as const) {
  test(`${role} sees shared-source facts and permitted controls`, async ({ page }, testInfo) => {
    const errors = await mockApi(page, { role, populated: true })
    await sourceApi(page)
    await page.goto('/tariffs?tariff=42%3ADynamic+tariff')
    const drawer = page.locator('.tariff-pane')
    await expect(drawer).toBeVisible()
    await expect(drawer).toContainText('Disabled')
    await expect(drawer).toContainText('Operator unavailable')
    // Where the source is fetched from and what it covers sit in a disclosure.
    await expect(drawer).not.toContainText('Across the platform')
    await drawer.getByText('Source details', { exact: true }).click()
    await expect(drawer).toContainText('Across the platform: 7 tariffs · 3 ZEVs')
    await expect(drawer).toContainText('Stored coverage may contain gaps')
    const operations = drawer.getByRole('link', { name: 'Manage source in platform admin' })
    if (role === 'admin') await expect(operations).toHaveAttribute('href', '/admin/dynamic-sources?source=s1')
    else await expect(operations).toHaveCount(0)
    // Admin/viewer cover the layout with and without maintenance controls.
    if (role !== 'manager') await checkWidths(page, `tariff-${role}`, name => testInfo.outputPath(name))
    await drawer.getByRole('button', { name: 'Close', exact: true }).click()
    if (role === 'viewer') {
      await expect(page.getByRole('button', { name: 'New Tariff', exact: true })).toHaveCount(0)
    } else {
      await page.getByRole('button', { name: 'New Tariff', exact: true }).click()
      await page.getByRole('button', { name: 'Create a new dynamic source', exact: true }).click()
      // An inline section of the pane's form, not a dialog over it.
      await expect(page.locator('.tariff-pane-section')).toContainText('URL')
      await expect(page.getByRole('dialog')).toHaveCount(0)
    }
    expect(errors).toEqual([])
  })
}

test('source operation links retain the selected source and allow returning to all sources', async ({ page }, testInfo) => {
  const errors = await mockApi(page)
  await sourceApi(page)
  await page.goto('/admin/dynamic-sources?source=s1&from=tariff#prices')
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await expect(page.locator('tbody')).toContainText('Shared operator source')
  await checkWidths(page, 'source-operations', name => testInfo.outputPath(name))
  await page.reload()
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await page.getByRole('button', { name: 'Show all sources', exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/dynamic-sources\?from=tariff#prices$/)
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await page.goto('/admin/dynamic-sources?source=removed#prices')
  await expect(page.locator('main')).toContainText('Source not found.')
  expect(errors).toEqual([])
})

test('tariff links reach source activity and its filters survive reload and clearing', async ({ page }, testInfo) => {
  const errors = await mockApi(page)
  await sourceApi(page)
  const requests = await auditApi(page)
  await page.goto('/tariffs?tariff=42%3ADynamic+tariff')
  await page.locator('.tariff-pane').getByRole('link', { name: 'Manage source in platform admin' }).click()
  await expect(page).toHaveURL(/\/admin\/dynamic-sources\?source=s1$/)
  await page.locator('tbody tr').getByRole('button', { name: 'Actions', exact: true }).click()
  await page.getByRole('menuitem', { name: 'View fetch log', exact: true }).click()
  await page.getByRole('dialog').getByRole('link', { name: 'View source activity' }).click()
  await expect(page).toHaveURL(/\/admin\/audit\?target_type=tariffs.DynamicTariffSource&target_id=s1$/)
  await expect.poll(() => requests.length).toBeGreaterThan(0)
  expect(requests.every(url => url.searchParams.get('target_id') === 's1'
    && url.searchParams.get('target_type') === 'tariffs.DynamicTariffSource')).toBe(true)
  await navigateMounted(page, `${page.url()}&from=tariff#activity`)
  await expect(page.getByLabel('Target ID', { exact: true })).toHaveValue('s1')
  await expect(page.locator('main')).toContainText('Activity across all communities and system operations')
  const beforeReload = requests.length
  await page.reload()
  await expect(page.getByLabel('Target ID', { exact: true })).toHaveValue('s1')
  await expect.poll(() => requests.length).toBeGreaterThan(beforeReload)
  expect(requests.slice(beforeReload).every(url => url.searchParams.get('target_id') === 's1'
    && url.searchParams.get('target_type') === 'tariffs.DynamicTariffSource')).toBe(true)
  await checkWidths(page, 'source-activity', name => testInfo.outputPath(name))
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click()
  await expect(page).toHaveURL(/\/admin\/audit\?from=tariff#activity$/)
  await expect(page.getByLabel('Target ID', { exact: true })).toHaveValue('')
  expect(errors).toEqual([])
})

test('mounted audit filter changes start at page one and close the previous event', async ({ page }) => {
  const errors = await mockApi(page)
  const requests = await auditApi(page, true)
  await page.goto('/admin/audit?target_type=tariffs.DynamicTariffSource&target_id=s1')
  for (const nextPage of ['2', '3']) {
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    await expect.poll(() => requests.at(-1)?.searchParams.get('page')).toBe(nextPage)
  }
  await page.locator('tbody tr').click()
  await expect(page.locator('.audit-drawer')).toBeVisible()
  await page.getByLabel('Target ID', { exact: true }).evaluate(input => { input.dataset.auditMounted = 'yes' })
  await navigateMounted(page, `${page.url()}&from=bookmark#activity`)
  await expect(page).toHaveURL(/from=bookmark#activity$/)
  await expect(page.locator('.audit-drawer')).toBeVisible()
  expect(requests.at(-1)?.searchParams.get('page')).toBe('3')

  const changed = new URL(page.url())
  changed.searchParams.set('target_id', 's2')
  await navigateMounted(page, changed.href, false)
  await expect(page.getByLabel('Target ID', { exact: true })).toHaveValue('s2')
  await expect(page.getByLabel('Target ID', { exact: true })).toHaveAttribute('data-audit-mounted', 'yes')
  await expect.poll(() => requests.filter(url => url.searchParams.get('target_id') === 's2').length).toBeGreaterThan(0)
  expect(requests.filter(url => url.searchParams.get('target_id') === 's2').map(url => url.searchParams.get('page'))).toEqual(['1'])
  await expect(page.locator('.audit-drawer')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('audit text typing stays local until Enter or blur commits one request', async ({ page }) => {
  const errors = await mockApi(page)
  const requests = await auditApi(page)
  await page.goto('/admin/audit?from=bookmark#activity')
  await expect.poll(() => requests.length).toBeGreaterThan(0)
  const input = page.getByLabel('Target ID', { exact: true })
  const before = requests.length
  await input.pressSequentially('source-1234', { delay: 20 })
  await expect(input).toHaveValue('source-1234')
  expect(requests).toHaveLength(before)
  await expect(page).toHaveURL(/\/admin\/audit\?from=bookmark#activity$/)
  await input.press('Enter')
  await expect.poll(() => requests.length).toBe(before + 1)
  expect(requests.at(-1)?.searchParams.get('target_id')).toBe('source-1234')

  await input.fill('source-5678')
  expect(requests).toHaveLength(before + 1)
  await page.getByLabel('Target type', { exact: true }).click()
  await expect.poll(() => requests.length).toBe(before + 2)
  expect(requests.at(-1)?.searchParams.get('target_id')).toBe('source-5678')
  expect(new URL(page.url()).searchParams.get('from')).toBe('bookmark')
  expect(new URL(page.url()).hash).toBe('#activity')
  expect(errors).toEqual([])
})

test('keyboard opens audit details and a new actor link closes them', async ({ page }) => {
  const errors = await mockApi(page)
  const requests = await auditApi(page, true)
  await page.goto('/admin/audit?actor=41&actorUsername=First')
  await expect.poll(() => requests.at(-1)?.searchParams.get('actor_user')).toBe('41')
  const summary = page.getByRole('button', { name: 'Source fetched', exact: true })
  await summary.focus()
  await summary.press('Enter')
  await expect(page.locator('.audit-drawer')).toBeVisible()
  await navigateMounted(page, '/admin/audit?actor=42&actorUsername=Second&from=account#activity')
  await expect.poll(() => requests.at(-1)?.searchParams.get('actor_user')).toBe('42')
  expect(requests.at(-1)?.searchParams.get('page')).toBe('1')
  await expect(page.getByRole('combobox', { name: 'Actor', exact: true })).toHaveValue('42')
  await expect(page.locator('.audit-drawer')).toHaveCount(0)
  await expect(page).toHaveURL(/\/admin\/audit\?from=account#activity$/)
  expect(errors).toEqual([])
})

test('source activity failure offers retry instead of empty history', async ({ page }) => {
  const state = { endpoint: '/audit/events/', failed: true }
  const errors = await mockApi(page, state)
  await sourceApi(page)
  await auditApi(page, true, state)
  await page.goto('/admin/dynamic-sources?source=s1')
  await page.locator('tbody tr').getByRole('button', { name: 'Actions', exact: true }).click()
  await page.getByRole('menuitem', { name: 'View fetch log', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('alert')).toContainText('Source activity could not be loaded')
  await expect(dialog).not.toContainText('No activity recorded yet')
  state.failed = false
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.locator('tbody')).toContainText('Source fetched')
  await expect(dialog.getByRole('alert')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('source activity retains cached events after a failed refresh', async ({ page }) => {
  const state = { endpoint: '/audit/events/', failed: false }
  const errors = await mockApi(page, state)
  await sourceApi(page)
  await auditApi(page, true, state)
  await page.goto('/admin/dynamic-sources?source=s1')
  await page.locator('tbody tr').getByRole('button', { name: 'Actions', exact: true }).click()
  await page.getByRole('menuitem', { name: 'View fetch log', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.locator('tbody')).toContainText('Source fetched')
  state.failed = true
  await refocusPage(page)
  await expect(dialog.getByRole('status')).toContainText('Showing the last loaded events')
  await expect(dialog.locator('tbody')).toContainText('Source fetched')
  await expect(dialog.getByRole('alert')).toHaveCount(0)
  state.failed = false
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(dialog.getByRole('status')).toHaveCount(0)
  await expect(dialog.locator('tbody')).toContainText('Source fetched')
  expect(errors).toEqual([])
})

test('source rows and totals survive a failed refetch', async ({ page }) => {
  const state = { endpoint: '/tariffs/dynamic-sources/', failed: false }
  const errors = await mockApi(page, state)
  await sourceApi(page, state)
  await page.goto('/admin/dynamic-sources')
  await expect(page.locator('tbody tr')).toHaveCount(2)
  state.failed = true
  await refocusPage(page)
  await expect(page.locator('main').getByRole('status')).toContainText('Could not refresh dynamic price sources. Showing the last loaded sources.')
  await expect(page.locator('main').getByRole('alert')).toHaveCount(0)
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await expect(page.locator('tbody')).toContainText('Shared operator source')
  await expect(page.locator('main .stat-card')).toHaveCount(4)
  state.failed = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.locator('main').getByRole('status')).toHaveCount(0)
  await expect(page.locator('tbody tr')).toHaveCount(2)
  expect(errors).toEqual([])
})

test('Audit and Export tabs preserve a dirty settings draft and its Save action', async ({ page }, testInfo) => {
  const errors = await mockApi(page, { role: 'manager' })
  await auditApi(page)
  await page.goto('/zev-settings/general?from=bookmark#community')
  const name = page.locator('[data-zev-field="name"] input')
  await expect(name).toHaveValue('Review ZEV')
  await name.fill('Unsaved community')
  await expect(page.locator('.zev-settings-save-bar')).toBeVisible()
  await page.getByRole('tab', { name: 'Audit log', exact: true }).click()
  await page.getByRole('tab', { name: 'Export / transfer', exact: true }).click()
  await expect(page).toHaveURL(/\/zev-settings\/export\?from=bookmark#community$/)
  await expect(page.getByRole('button', { name: 'Export ZEV', exact: true })).toHaveClass(/button-secondary/)
  await expect(page.locator('.zev-settings-save-bar').getByRole('button', { name: 'Save changes', exact: true })).toBeVisible()
  await checkWidths(page, 'dirty-community-export', name => testInfo.outputPath(name))
  await page.getByRole('tab', { name: 'Audit log', exact: true }).click()
  await expect(page).toHaveURL(/\/zev-settings\/audit\?from=bookmark#community$/)
  await expect(page.locator('.zev-settings-save-bar')).toBeVisible()
  await page.getByRole('tab', { name: 'General', exact: true }).click()
  await expect(name).toHaveValue('Unsaved community')
  expect(errors).toEqual([])
})

test('a viewer exports a disabled community and opens its audit tab', async ({ page }, testInfo) => {
  const errors = await mockApi(page, { role: 'viewer', zevs: [{ id: '42', name: 'Review ZEV', disabled_at: '2026-09-30T12:00:00Z' }] })
  await auditApi(page)
  const archive = Buffer.from('UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==', 'base64')
  const exports: URL[] = []
  await page.route('**/api/v1/zev/zevs/transfer-sections/', route => route.request().method() === 'GET'
    ? route.fulfill({ json: { sections: DEFAULT_SECTIONS } }) : route.fallback())
  await page.route('**/api/v1/zev/zevs/42/export/**', route => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() !== 'GET' || url.pathname !== '/api/v1/zev/zevs/42/export/') return route.fallback()
    exports.push(url)
    return route.fulfill({ contentType: 'application/zip', headers: { 'content-disposition': 'attachment; filename="review-zev.zip"' }, body: archive })
  })
  await page.goto('/zev-settings/export?from=bookmark#community')
  const exportButton = page.getByRole('button', { name: 'Export ZEV', exact: true })
  await expect(exportButton).toBeVisible()
  await expect(exportButton).toHaveClass(/button-primary/)
  await expect(page.locator('main')).toContainText('Export Review ZEV as an archive')
  await checkWidths(page, 'community-export', name => testInfo.outputPath(name))
  await exportButton.click()
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('dialog').getByRole('button', { name: 'Download archive', exact: true }).click(),
  ])
  expect(exports).toHaveLength(1)
  expect(exports[0].searchParams.get('sections')).toBe('zev,participants,metering_points,tariffs')
  expect(download.suggestedFilename()).toBe('review-zev.zip')
  expect(await download.failure()).toBeNull()
  expect(await readFile((await download.path())!)).toEqual(archive)
  await page.getByRole('tab', { name: 'Audit log', exact: true }).click()
  await expect(page).toHaveURL(/\/zev-settings\/audit\?from=bookmark#community$/)
  await expect(page.locator('main')).toContainText('Activity for Review ZEV')
  expect(errors).toEqual([])
})

test('annual-document aliases retain participant context and document access', async ({ page }) => {
  const errors = await mockApi(page, { role: 'participant' })
  await page.route('**/api/v1/invoices/invoices/annual-statement/**', route => route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF' }))
  await page.goto('/billing/statements?year=2025&from=bookmark#documents')
  await expect(page).toHaveURL(/\/reports\?year=2025&from=bookmark#documents$/)
  await expect(page.getByRole('button', { name: /Download.*PDF/ }).first()).toBeVisible()
  const obsoletePreview = await page.locator('main iframe').first().getAttribute('src')
  expect(obsoletePreview).toMatch(/^blob:/)
  await page.goto('/me/statement')
  await expect(page.getByRole('button', { name: /Download.*PDF/ }).first()).toBeVisible()
  // Navigation can cancel an obsolete preview request or Chromium's PDF viewer.
  expect(errors.filter(error => !(error.endsWith('net::ERR_ABORTED')
    && (error.includes('/annual-statement/')
      || error === `GET ${obsoletePreview}: net::ERR_ABORTED`
      || error.startsWith('GET chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/'))))).toEqual([])
})

test('a failed source load offers retry without claiming there are zero sources', async ({ page }) => {
  const state = { endpoint: '/tariffs/dynamic-sources/', failed: true }
  const errors = await mockApi(page, state)
  await page.goto('/admin/dynamic-sources?source=s1#prices')
  // Allow the query client's automatic retry backoff to finish.
  await expect(page.locator('main').getByRole('alert')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('main .stat-card')).toHaveCount(0)
  await expect(page.locator('main .empty-state')).toHaveCount(0)
  state.failed = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.locator('main .stat-card')).toHaveCount(4)
  await expect(page.locator('main')).toContainText('Source not found.')
  expect(new URL(page.url()).hash).toBe('#prices')
  expect(errors).toEqual([])
})
