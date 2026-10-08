import { expect, test } from '@playwright/test'
import { apiErrors, mockApi, type ApiState } from './page-anatomy-fixtures'
import type { Invoice, InvoicePeriodParticipantRow } from '../src/types/api'

// Check presentation and scope through the real router with controlled workflow states.
test.use({ storageState: { cookies: [], origins: [] }, locale: 'en-CH' })
test.afterEach(({ page }) => expect(apiErrors.get(page) ?? []).toEqual([]))

const period = { period_start: '2026-09-01', period_end: '2026-09-30' }
const invoice: Invoice = {
  id: '1', invoice_number: 'R-1', zev: '42', zev_name: 'Review ZEV',
  participant: 'p1', participant_name: 'Participant A', ...period,
  status: 'draft', total_chf: '123.45', pdf_status: 'ready', pdf_url: '/stored.pdf',
}
const row: InvoicePeriodParticipantRow = {
  participant_id: 'p1', participant_name: 'Participant A', participant_email: 'participant@example.test',
  participant_kind: 'person', participant_name_addition: '', participant_valid_from: '2026-01-01',
  participant_valid_to: null, party_id: 'party-1', metering_point_labels: [],
  invoice, generation_eligibility: null, metering_data_complete: true,
  metering_points_total: 1, metering_points_with_data: 1, missing_meter_ids: [],
}
const rows: InvoicePeriodParticipantRow[] = [
  row,
  { ...row, participant_id: 'p2', participant_name: 'Participant B', invoice: {
    ...invoice, id: '2', invoice_number: 'R-2', status: 'approved', pdf_url: null, pdf_status: 'pending', last_email_status: 'pending',
  } },
  { ...row, participant_id: 'p3', participant_name: 'Participant C', invoice: {
    ...invoice, id: '3', invoice_number: 'R-3', status: 'sent', pdf_url: null, pdf_status: 'failed', last_email_status: 'failed',
  } },
]

// Long identity, several meters, every issue at once and a large amount.
const demanding: InvoicePeriodParticipantRow = {
  ...row, participant_id: 'p4', participant_name: 'Genossenschaft Sonnenhof Wohnbau und Gewerbe Oberwinterthur',
  participant_kind: 'organisation', participant_name_addition: 'c/o Verwaltung Muster & Partner Treuhand GmbH',
  participant_email: '', participant_valid_to: '2026-09-17', party_id: 'party-coop',
  metering_point_labels: ['Gewerbefläche Erdgeschoss Nord', 'Tiefgarage Einstellplatz 117', 'Allgemeinstrom Treppenhaus B'],
  metering_data_complete: false, metering_points_total: 3, metering_points_with_data: 1,
  missing_meter_ids: ['CH-1001', 'CH-1002'],
  missing_meter_details: [{ meter_id: 'CH-1001', missing_days: 17 }, { meter_id: 'CH-1002', missing_days: 3 }],
  invoice: { ...invoice, id: '4', invoice_number: 'R-2026-09-000004', status: 'approved', total_chf: '1234567.85',
    pdf_url: null, pdf_status: 'failed', last_email_status: 'failed' },
}
const layoutRows = [...rows, demanding, { ...demanding, participant_id: 'p5', participant_valid_to: null,
  metering_point_labels: ['Parkplatz 3'], metering_data_complete: true, metering_points_with_data: 3,
  missing_meter_ids: [], missing_meter_details: [], invoice: { ...demanding.invoice!, id: '5', invoice_number: 'R-5', pdf_status: 'ready', pdf_url: '/r5.pdf', last_email_status: null } }]

for (const language of ['en', 'de', 'fr', 'it']) {
  test(`compact invoice controls fit desktop and narrow widths in ${language}`, async ({ page }, testInfo) => {
    await mockApi(page, { periodRows: layoutRows })
    await page.addInitScript(lang => localStorage.setItem('openzev.language', lang), language)
    await page.setViewportSize({ width: 1280, height: 768 })
    await page.goto('/billing/invoices')
    const table = page.locator('main table')
    await expect(table.locator('tbody tr')).toHaveCount(5)
    await expect(table.locator('thead th')).toHaveCount(4)
    // Nothing in a cell spills over its neighbours, however long.
    const demandingRow = table.locator('tbody tr').filter({ hasText: 'Sonnenhof' }).first()
    await expect(demandingRow.locator('.invoice-row-issues > *')).toHaveCount(4)
    await expect(demandingRow).toContainText('Tiefgarage Einstellplatz 117')
    for (const cell of await demandingRow.locator('td').all()) {
      expect(await cell.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
    }
    // Enough of the first normal row is visible to start reviewing without scrolling.
    expect((await table.locator('tbody tr').first().boundingBox())!.y).toBeLessThan(560)
    // The period stepper and the batch actions each keep to one line (longer
    // languages move the actions below the stepper); the filters take another.
    for (const group of ['.period-selector', '.invoice-batch-actions']) {
      const tops = await page.locator(`.invoice-command-bar ${group} button`).evaluateAll(elements =>
        elements.map(element => Math.round(element.getBoundingClientRect().top)))
      expect(new Set(tops).size).toBe(1)
    }
    const filters = page.locator('.filter-tab')
    await expect(filters).toHaveCount(5)
    const positions = await filters.evaluateAll(elements => elements.map(element => element.getBoundingClientRect().top))
    expect(new Set(positions).size).toBe(1)
    // Each row is one line of actions: the progress icons and buttons never wrap.
    for (const cell of await table.locator('tbody td.invoice-actions-cell').all()) {
      const buttons = await cell.locator('button').evaluateAll(elements => elements.map(element => Math.round(element.getBoundingClientRect().top)))
      expect(new Set(buttons).size).toBe(1)
    }
    await page.screenshot({ path: testInfo.outputPath(`billing-${language}-1280.png`), fullPage: true })

    await page.setViewportSize({ width: 400, height: 850 })
    await expect.poll(() => page.locator('aside').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
    for (const control of await page.locator('.invoice-command-bar button, .filter-tab, .invoice-rows button').all()) {
      const box = await control.boundingBox()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(401)
    }
    // Rows become cards: the amount sits beside the name, never off-screen.
    const firstRow = table.locator('tbody tr').first()
    expect(await firstRow.evaluate(element => getComputedStyle(element).display)).toBe('grid')
    // Cards stay a table for assistive technology, column headers included.
    await expect(page.getByRole('table')).toHaveCount(1)
    await expect(page.getByRole('columnheader')).toHaveCount(4)
    await expect(page.getByRole('row')).toHaveCount(6)
    const name = await firstRow.locator('.invoice-row-name').boundingBox()
    const total = await firstRow.locator('.invoice-row-total').boundingBox()
    expect(Math.abs(name!.y - total!.y)).toBeLessThan(8)
    // The amount header is out of sight, so the card names the currency.
    await expect(firstRow.locator('.invoice-row-total')).toContainText(/^CHF /)
    for (const total of await table.locator('.invoice-row-total').all()) {
      const box = await total.boundingBox()
      expect(box!.x + box!.width).toBeLessThanOrEqual(401)
    }
    await filters.nth(1).focus()
    await page.keyboard.press('Space')
    await expect(filters.nth(1)).toHaveAttribute('aria-pressed', 'true')
    await expect(table.locator('tbody tr')).toHaveCount(1)
    await expect(filters.nth(1)).toBeFocused()
    await page.keyboard.press('Space')
    await expect(table.locator('tbody tr')).toHaveCount(5)
    await page.screenshot({ path: testInfo.outputPath(`billing-${language}-400.png`), fullPage: true })
  })
}

for (const scope of ['viewer', 'disabled-manager'] as const) {
  test(`${scope} retains covering and conflict navigation without writes`, async ({ page }) => {
    await mockApi(page, {
      role: scope === 'viewer' ? 'viewer' : 'manager',
      zevs: [{ id: '42', name: 'Review ZEV', disabled_at: scope === 'disabled-manager' ? '2026-10-01' : null }],
      periodRows: [
        { ...row, invoice: null, generation_eligibility: { state: 'covered', invoice_id: '1', invoice_number: 'R-1' } },
        { ...row, participant_id: 'p2', participant_name: 'Participant B', invoice: null,
          generation_eligibility: { state: 'blocked', invoice_id: '1', invoice_number: 'R-1' },
          metering_data_complete: false, metering_points_with_data: 0, missing_meter_ids: ['CH-MISSING'],
          missing_meter_details: [{ meter_id: 'CH-MISSING', missing_days: 3 }],
        },
        { ...row, participant_id: 'p3', participant_name: 'Participant C', invoice: { ...invoice, status: 'cancelled' },
          generation_eligibility: { state: 'covered', invoice_id: '1', invoice_number: 'R-1' } },
      ],
    })
    await page.goto('/billing/invoices')
    await expect(page.locator('tbody tr')).toHaveCount(3)
    // A covered row names the invoice that bills it, as a link.
    await expect(page.locator('.invoice-progress-covered')).toHaveCount(2)
    await expect(page.locator('.invoice-progress-covered').first()).toContainText('Already billed R-1')
    await expect(page.getByRole('button', { name: 'Review conflict', exact: true })).toHaveCount(1)
    await expect(page.locator('.invoice-row-issues').getByText('Overlaps locked invoice R-1', { exact: true })).toBeVisible()
    await expect(page.getByText('CH-MISSING (3 missing days)')).toBeVisible()
    await expect(page.locator('main .invoice-batch-actions button')).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'Download all PDFs (1)', exact: true })).toBeEnabled()
    await expect(page.locator('.invoice-batch-actions, .invoice-row-actions').getByRole('button', { name: /Generate|Approve|Send/ })).toHaveCount(0)
    // Filtering stays available to read-only accounts.
    await page.getByRole('button', { name: 'Issues 1', exact: true }).click()
    await expect(page.locator('tbody tr')).toHaveCount(1)
    await expect(page.locator('tbody')).toContainText('Participant B')
    await page.getByRole('button', { name: 'All 3', exact: true }).click()
    await expect(page.locator('tbody tr')).toHaveCount(3)
    await page.locator('.invoice-progress-covered a').first().click()
    await expect(page).toHaveURL(/\/billing\/invoices\/1$/)
    await page.getByRole('link', { name: 'Back to Invoices', exact: true }).click()
    await expect(page).toHaveURL(/period_start=2026-09-01&period_end=2026-09-30/)
  })
}

test('row filtering leaves the whole-period batch payload and pending controls intact', async ({ page }) => {
  const state: ApiState = { periodRows: rows.map(entry => ({ ...entry })) }
  await mockApi(page, state)
  let finish!: () => void
  const pending = new Promise<void>(resolve => { finish = resolve })
  await page.route('**/api/v1/invoices/invoices/approve-all/', async route => {
    expect(route.request().postDataJSON()).toEqual({ zev_id: '42', ...period })
    await pending
    state.periodRows![0] = { ...row, invoice: { ...invoice, status: 'approved' } }
    await route.fulfill({ json: { approved: 1 } })
  })
  await page.goto('/billing/invoices')
  const filters = page.locator('.filter-tab')
  await expect(filters).toHaveCount(5)
  // Show approved rows, while the recommended approval acts on the hidden draft.
  await filters.nth(2).click()
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await expect(page.locator('tbody')).toContainText('Participant B')
  await expect(page.getByText(/Batch actions apply to the whole period/)).toBeVisible()
  const request = page.waitForRequest('**/api/v1/invoices/invoices/approve-all/')
  await page.getByRole('button', { name: 'Approve 1 invoice', exact: true }).click()
  await request
  await expect(page.getByRole('button', { name: 'Approve 1 invoice', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Download all PDFs (1)', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'More batch actions', exact: true })).toBeDisabled()
  finish()
  await expect(page.locator('tbody tr')).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Send 2 invoices', exact: true })).toBeEnabled()
})

test('a PDF retry leaves the Issues filter and count together', async ({ page }) => {
  const failed: InvoicePeriodParticipantRow = { ...row, participant_id: 'p2', participant_name: 'Participant B',
    invoice: { ...invoice, id: '2', invoice_number: 'R-2', pdf_url: null, pdf_status: 'failed' } }
  const state: ApiState = { periodRows: [row, failed] }
  await mockApi(page, state)
  let finish!: () => void
  const pending = new Promise<void>(resolve => { finish = resolve })
  await page.route('**/api/v1/invoices/invoices/2/generate-pdf/', async route => {
    await pending
    state.periodRows = [row, { ...failed, invoice: { ...failed.invoice!, pdf_url: '/r-2.pdf', pdf_status: 'ready' } }]
    await route.fulfill({ json: { pdf_url: '/r-2.pdf' } })
  })
  await page.goto('/billing/invoices')
  await page.getByRole('button', { name: 'Issues 1', exact: true }).click()
  await expect(page.locator('tbody tr')).toHaveCount(1)
  await page.locator('tbody').getByRole('button', { name: 'More', exact: true }).click()
  await page.getByRole('menuitem', { name: /generate PDF/i }).click()
  // While the retry runs the old failure is no longer news: not in the row,
  // not in the filter, not in its count.
  await expect(page.locator('tbody tr')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Issues 0', exact: true })).toBeVisible()
  finish()
  await page.getByRole('button', { name: 'All 2', exact: true }).click()
  await expect(page.locator('.invoice-row-issues')).toHaveCount(0)
  // Released, the empty Issues tab is left out.
  await expect(page.getByRole('button', { name: /^Issues/ })).toHaveCount(0)
})

for (const leavePeriod of [false, true]) {
  test(`queued batch generation ${leavePeriod ? 'stops watching when the period changes' : 'keeps polling before invoice rows exist'}`, async ({ page }) => {
    const state: ApiState = { fakeTimers: true, periodRows: [{ ...row, invoice: null,
      generation_eligibility: { state: 'eligible', invoice_id: null, invoice_number: null },
    }] }
    await mockApi(page, state)
    let queued = false
    let polls = 0
    await page.route('**/api/v1/invoices/invoices/generate-all/', async route => {
      expect(route.request().postDataJSON()).toEqual({ zev_id: '42', ...period })
      queued = true
      await route.fulfill({ status: 202, json: { queued: true, participant_count: 1 } })
    })
    await page.route('**/api/v1/invoices/invoices/period-overview/**', async route => {
      if (queued) polls++
      await route.fallback()
    })
    await page.goto('/billing/invoices')
    const firstRefresh = page.waitForResponse(response => queued && response.url().includes('/invoices/invoices/period-overview/') && response.ok())
    await page.getByRole('button', { name: 'Generate 1 invoice', exact: true }).click()
    await firstRefresh
    const status = page.locator('main p.visually-hidden[role="status"]')
    // The row shows the work; only a screen reader hears the count.
    await expect(page.locator('.invoice-row-pending')).toHaveText('Creating invoice\u2026')
    await expect(status).toHaveText('Preparing 1 invoice or PDF\u2026')
    await expect(page.getByRole('button', { name: 'Generate 1 invoice', exact: true })).toBeDisabled()
    const accepted = polls
    if (leavePeriod) {
      state.invoicePeriod = ['2026-10-01', '2026-10-31']
      await page.getByRole('button', { name: 'Next period', exact: true }).click()
      await expect(page).toHaveURL(/period_start=2026-10-01&period_end=2026-10-31/)
      await expect(status).toHaveText('')
    } else {
      // Still polling while no invoice row exists.
      await page.clock.fastForward(2_500)
      await expect.poll(() => polls).toBeGreaterThan(accepted)
      state.periodRows = [row]
      await page.clock.fastForward(2_500)
      await expect(page.getByRole('link', { name: 'R-1', exact: true })).toBeVisible()
      await expect(status).toHaveText('')
    }
    const settled = polls
    // Jumping past several intervals fires any live poll: there is none left.
    await page.clock.fastForward(10_000)
    // Let anything those timers started reach the network before counting.
    await page.waitForLoadState('networkidle')
    expect(polls).toBe(settled)
  })
}

test('queued generation that never arrives says so at the deadline', async ({ page }) => {
  const state: ApiState = { fakeTimers: true, periodRows: [{ ...row, invoice: null,
    generation_eligibility: { state: 'eligible', invoice_id: null, invoice_number: null },
  }] }
  await mockApi(page, state)
  await page.route('**/api/v1/invoices/invoices/generate-all/', route =>
    route.fulfill({ status: 202, json: { queued: true, participant_count: 1 } }))
  await page.goto('/billing/invoices')
  const generate = page.getByRole('button', { name: 'Generate 1 invoice', exact: true })
  await generate.click()
  await expect(page.locator('.invoice-row-pending')).toHaveText('Creating invoice…')
  const notice = page.getByText('Processing has not finished yet.', { exact: false })
  await expect(notice).toHaveCount(0)
  // The worker never delivers: past the 90-second watch the page says so
  // instead of quietly showing the row as never requested.
  await page.clock.fastForward(91_000)
  await expect(notice).toBeVisible()
  await expect(page.locator('.invoice-row-pending')).toHaveCount(0)
  await expect(generate).toBeEnabled()
  // Changing period clears it: it belongs to the period that queued the work.
  state.invoicePeriod = ['2026-10-01', '2026-10-31']
  await page.getByRole('button', { name: 'Next period', exact: true }).click()
  await expect(notice).toHaveCount(0)
})
