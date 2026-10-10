/**
 * Automated screenshot generation for user-guide documentation.
 *
 * Run:
 *   cd frontend
 *   npm run screenshots
 *
 * Screenshots are saved to: docs/user-guide/screenshots/
 *
 * Environment variables:
 *   SCREENSHOT_BASE_URL  – default http://localhost:8080
 *   SCREENSHOT_USER      – default "admin"
 *   SCREENSHOT_PASSWORD  – default "admin1234"
 */
import { test, expect, type Page } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'
import type { DynamicTariffSource, TariffSeries } from '../src/types/api'
import {
  assertPdfLoaded,
  closePdfSidebar,
  findDemoInvoice,
  getAdminToken,
  goToPreviousPeriod,
  impersonateDemoParticipant,
  navigateTo,
  pinDemoZev,
  resolveDemoZevId,
  screenshotFull as captureFull,
  screenshotViewport as captureViewport,
  API_BASE,
  DEMO_ZEV_NAME,
  MISSING_DEMO_ZEV,
  SECOND_DEMO_ZEV_NAME,
} from './helpers'

const DEMO_ZEV_NAMES = [DEMO_ZEV_NAME, SECOND_DEMO_ZEV_NAME]


const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const SCREENSHOT_DIR = path.resolve(__dirname, '../../docs/user-guide/screenshots')

const screenshotFull = (page: Page, name: string) => captureFull(page, SCREENSHOT_DIR, name)
const screenshotViewport = (page: Page, name: string) => captureViewport(page, SCREENSHOT_DIR, name)

const DEMO_DYNAMIC_TARIFF = 'Netznutzung dynamisch'
const SEED_HINT = 'run `manage.py seed_demo` with its default end date before capturing screenshots'

/** Fail early when the seeded dynamic tariff or its prices are missing. */
async function requireDemoDynamicSource(page: Page): Promise<DynamicTariffSource> {
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  const zevId = await resolveDemoZevId(page)
  const response = await page.request.get(`${API_BASE}/tariffs/tariffs/series/?zev_id=${zevId}`, { headers })
  expect(response.ok(), `Tariff series request failed (${response.status()})`).toBe(true)
  const series = await response.json() as TariffSeries[]
  const tariff = series.find(row => row.name === DEMO_DYNAMIC_TARIFF)?.versions[0]
  expect(tariff?.dynamic_source, `Dynamic demo tariff missing — ${SEED_HINT}`).toBeTruthy()
  const sourceResponse = await page.request.get(`${API_BASE}/tariffs/dynamic-sources/${tariff!.dynamic_source}/`, { headers })
  expect(sourceResponse.ok(), `Dynamic source request failed (${sourceResponse.status()})`).toBe(true)
  const source = await sourceResponse.json() as DynamicTariffSource
  expect(source.point_count, `Dynamic demo prices missing — ${SEED_HINT}`).toBeGreaterThan(0)
  return source
}

// ---------------------------------------------------------------------------
// Screenshot tests — one test per page / state
//
// Every test starts from the authenticated storage state the `setup` project
// saved (see screenshots.config.ts), so tests must not log in themselves.
//
// No test may change data another capture shows; shared fixtures belong in
// capture.setup.ts.
// ---------------------------------------------------------------------------

// Keep this outside the authenticated suite: its beforeEach pins the demo ZEV.
test.describe('Unauthenticated Screenshots', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('01-login', async ({ page }) => {
    await navigateTo(page, '/login')
    const cookies = await page.context().cookies(API_BASE)
    expect(cookies.some(cookie => cookie.name === 'openzev_access'),
      'Login capture must stay signed out').toBe(false)
    await page.waitForSelector('form')
    await screenshotFull(page, '01-login')
  })
})

test.describe('User Guide Screenshots', () => {
  test.beforeEach(async ({ page }) => {
    expect(await pinDemoZev(page), MISSING_DEMO_ZEV).toBe(true)
  })

  // 02 — Manager Overview
  test('02-dashboard', async ({ page }) => {
    await navigateTo(page, '/')
    await page.waitForSelector('#billing-periods', { timeout: 15_000 })
    await screenshotFull(page, '02-dashboard')
  })

  // 02c — Manager Energy balance (the former dashboard statistics surface)
  test('02c-energy-balance', async ({ page }) => {
    await navigateTo(page, '/dashboard')
    await page.waitForSelector('.period-selector', { timeout: 10_000 })
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/dashboard-summary/') && response.ok()),
      goToPreviousPeriod(page),
    ])
    await page.waitForSelector('.sankey-participant-label', { timeout: 15_000 })
    await screenshotFull(page, '02c-energy-balance')
  })

  // 02b — Participant Dashboard (via impersonation)
  test('02b-participant-dashboard', async ({ page }) => {
    await impersonateDemoParticipant(page)
    await navigateTo(page, '/')
    await page.waitForSelector('.card, .stat-card', { timeout: 10_000 })
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/dashboard-summary/') && response.ok()),
      goToPreviousPeriod(page),
    ])
    await page.waitForSelector('.sankey-participant-label', { timeout: 15_000 })
    await screenshotFull(page, '02b-participant-dashboard')
  })

  // 03 — Participants
  test('03-participants', async ({ page }) => {
    await navigateTo(page, '/participants')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '03-participants')
  })

  // 03b — Participant create form with the allocation weight filled in, so
  // the guide can show how a weighted cost split is entered. Weight 2 is what
  // seed_demo gives most flats.
  test('03b-participant-allocation-weight', async ({ page }) => {
    await navigateTo(page, '/participants')
    await page.waitForSelector('table, .card', { timeout: 10_000 })

    await page
      .getByRole('button', {
        name: /new participant|neuer teilnehmer|nouveau participant|nuovo partecipante/i,
      })
      .click()
    // The modal is up once its footer button is reachable; waiting on the
    // overlay's inline z-index would tie the test to the modal's styling.
    const createButton = page.getByRole('button', { name: /create|erstellen|créer|creare/i })
    await createButton.waitFor({ timeout: 5_000 })

    // The weight input sits inside its label, so it is reachable by the
    // translated label text instead of being "the only numeric input".
    await page
      .getByLabel(/allocation weight|zuteilungsgewicht|attribution|allocazione/i)
      .fill('2')
    // Scroll to the modal's footer so the weight field, its hint text and the
    // action buttons share the frame instead of the field hugging the edge.
    await createButton.scrollIntoViewIfNeeded()
    await page.waitForTimeout(300)
    await screenshotViewport(page, '03b-participant-allocation-weight')
  })

  // 03c — The participant form for an organisation: the type switch, the
  // organisation name and the contact person, and the second name line.
  test('03c-participant-organisation', async ({ page }) => {
    await navigateTo(page, '/participants')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await page
      .getByRole('button', {
        name: /new participant|neuer teilnehmer|nouveau participant|nuovo partecipante/i,
      })
      .click()
    await page.locator('select:has(option[value="organisation"])').selectOption('organisation')
    await page.locator('input[name="organisation_name"]').fill('Bäckerei Muster GmbH')
    await page.locator('input[name="first_name"]').fill('Lea')
    await page.locator('input[name="last_name"]').fill('Muster')
    await page.locator('input[name="name_addition"]').fill('Filiale Aarestrasse')
    await page.waitForTimeout(300)
    await screenshotViewport(page, '03c-participant-organisation')
  })

  // 04 — Metering Points
  test('04-metering-points', async ({ page }) => {
    await navigateTo(page, '/metering-points')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '04-metering-points')
  })

  // 04b — Metering Points with Assign Participant modal, captured against the
  // seeded unassigned metering point (CH-DEMO-CONS-0003) — no fixture needed.
  test('04b-metering-points-assign', async ({ page }) => {
    await navigateTo(page, '/metering-points')
    await page.waitForSelector('.metering-point-card, table, .card', { timeout: 10_000 })

    const pointCard = page.locator('.metering-point-card').filter({ hasText: 'CH-DEMO-CONS-0003' }).first()
    await expect(pointCard).toBeVisible({ timeout: 10_000 })

    const assignBtn = pointCard.getByRole('button', {
      name: /assign|zuweisen|assigner|assegna/i,
    })
    await assignBtn.click()

    // Wait for modal overlay to appear
    await page.waitForSelector('div[style*="z-index: 1000"]', { timeout: 5_000 })
    await page.waitForTimeout(500)
    await screenshotViewport(page, '04b-metering-points-assign')
  })

  // 05 — Metering Data / Charts (with a metering point selected)
  test('05-metering-data', async ({ page }) => {
    await navigateTo(page, '/metering/chart')
    await page.waitForSelector('.card', { timeout: 10_000 })
    // Select the first metering point that can carry readings — skipping the
    // "whole ZEV total" option (value __zev_total__, see
    // ALL_METERING_POINTS_VALUE in MeteringChartPage.tsx), which is the
    // management default and the first option, and would hide the Raw
    // Readings Table this screenshot is meant to show.
    const mpSelect = page.locator('select').first()
    const options = mpSelect.locator('option')
    await expect(mpSelect.locator('option[value]:not([value=""]):not([value="__zev_total__"])').first(),
      `Demo metering points missing — ${SEED_HINT}`).toBeAttached()
    const count = await options.count()
    for (let i = 0; i < count; i++) {
      const label = await options.nth(i).textContent()
      const value = await options.nth(i).getAttribute('value')
      if (value && value !== '__zev_total__' && label) {
        await mpSelect.selectOption(value)
        await page.waitForTimeout(1000)

        // Step back to the last complete period: the current one holds only the
        // days elapsed so far, which makes for a sparse chart.
        await goToPreviousPeriod(page)

        // Safety net if the seeded window ever moves: keep stepping back until a
        // period with readings is found, so the capture never depends on today.
        const prevPeriod = page.locator('button:has(svg[data-icon="arrow-left"])').first()
        for (let attempt = 0; attempt < 5; attempt++) {
          if (await page.locator('.recharts-wrapper').count()) break
          await prevPeriod.click()
          await page.waitForTimeout(1500)
        }
        break
      }
    }

    await page.waitForSelector('.recharts-wrapper', { timeout: 15_000 })
    await page.waitForTimeout(1000)
    await screenshotFull(page, '05-metering-data')
  })

  // 06 — ZEV Settings
  test('06-zev-settings', async ({ page }) => {
    await navigateTo(page, '/zev-settings')
    await page.waitForSelector('form, .card', { timeout: 10_000 })
    await screenshotFull(page, '06-zev-settings')
  })

  // Phase 3 surfaces have their own guide captures so tab placement and
  // selected-community/platform context stay visible in the documentation.
  for (const [name, route] of [
    ['06b-zev-billing-settings', '/zev-settings/billing'],
    ['06d-zev-people', '/zev-settings/people'],
    ['08e-billing-emails', '/billing/emails'],
    ['10b-admin-health', '/admin/health'],
  ]) {
    test(name, async ({ page }) => {
      await navigateTo(page, route)
      await expect(page.locator('[role="tab"][aria-selected="true"]')).toBeVisible()
      await screenshotFull(page, name)
    })
  }

  test('06c-zev-documents-settings', async ({ page }) => {
    await navigateTo(page, '/zev-settings/documents')
    await expect(page.locator('[data-zev-field="email_body_template"] textarea')).toBeVisible()
    await page.locator('[data-zev-field="email_body_template"] button').click()
    await expect(page.locator('[data-zev-field="email_body_template"] .zev-email-default-preview')).toBeVisible()
    await screenshotFull(page, '06c-zev-documents-settings')
  })

  // 07 — Tariffs
  test('07-tariffs', async ({ page }) => {
    await navigateTo(page, '/tariffs')
    await page.waitForSelector('.tariff-card, .empty-state', { timeout: 10_000 })
    await screenshotFull(page, '07-tariffs')
  })

  // 07b — A tariff's version history and price chart, both in its detail
  // drawer (opened from the card, but rendered as a page-level sibling —
  // not inside article.tariff-card — so it's located from `page`, not `card`).
  test('07b-tariff-versions', async ({ page }) => {
    await navigateTo(page, '/tariffs')
    const card = page.locator('article.tariff-card').filter({ hasText: 'Grid Energy HT/NT' }).first()
    await card.waitFor({ timeout: 10_000 })
    // "View details" is the only button on the card carrying aria-expanded.
    await card.getByRole('button', { expanded: false }).click()
    const drawer = page.locator('.tariff-drawer')
    // Waiting on the chart rather than the history: it renders only for a series
    // with more than one version, so it also asserts the seed still has them.
    await drawer.locator('.tariff-price-history').waitFor({ timeout: 10_000 })
    await page.waitForTimeout(1000)  // let Recharts finish laying out
    await screenshotFull(page, '07b-tariff-versions')
  })

  // 07d — A dynamic tariff's detail drawer, showing its Dynamic badge and
  // locally seeded price history (stats, chart and point table render inline).
  test('07d-tariff-dynamic-source', async ({ page }) => {
    await requireDemoDynamicSource(page)
    await navigateTo(page, '/tariffs')
    const card = page.locator('article.tariff-card').filter({ hasText: DEMO_DYNAMIC_TARIFF }).first()
    await card.waitFor({ timeout: 10_000 })
    await card.getByRole('button', { expanded: false }).click()
    const drawer = page.locator('.tariff-drawer')
    await expect(drawer.locator('.recharts-surface'), `Dynamic price chart missing — ${SEED_HINT}`).toBeVisible()
    await expect(drawer.locator('tbody tr').first()).toBeVisible()
    await screenshotFull(page, '07d-tariff-dynamic-source')
  })

  // 07e was the fetched-price history modal opened from a dynamic tariff's
  // card: chart, stats, coverage. That modal is gone — the same content now
  // renders inline in the drawer 07d already captures — so there is nothing
  // left for a separate shot to show. Removed along with
  // 07e-dynamic-price-history.png.

  // 08 — Invoices (period overview)
  test('08-invoices', async ({ page }) => {
    await navigateTo(page, '/billing/invoices')
    await page.waitForSelector('.period-selector', { timeout: 10_000 })
    // The page opens on the last complete period — exactly where seed_demo
    // bills — so no period navigation here (see goToPreviousPeriod docstring).
    await screenshotFull(page, '08-invoices')
  })

  // 08b — Invoice Detail page
  test('08b-invoice-detail', async ({ page }) => {
    const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
    const invoice = await findDemoInvoice(page.request, headers)
    expect(invoice.pdf_url, 'Invoice PDF missing — capture.setup.ts renders it').toBeTruthy()

    // screenshotFull grows the viewport to the content height, so the embedded
    // PDF viewer — which Chromium only paints inside the viewport — renders.
    await navigateTo(page, `/billing/invoices/${invoice.id}`)
    await page.waitForSelector('.invoice-figures', { timeout: 10_000 })
    await page.waitForSelector('iframe[title]', { timeout: 15_000 })
    await assertPdfLoaded(page)
    await closePdfSidebar(page)
    await screenshotFull(page, '08b-invoice-detail')
  })

  // 08c — Participant My Invoices (via impersonation)
  test('08c-my-invoices', async ({ page }) => {
    await impersonateDemoParticipant(page, { requireSentInvoice: true })
    await navigateTo(page, '/me/invoices')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    // Rows appear even without a PDF — the state the guide's list section shows.
    await page.waitForSelector('tbody tr, .invoice-row', { timeout: 10_000 })
    await page.waitForTimeout(400)
    await screenshotFull(page, '08c-my-invoices')
  })

  // 09 — Imports
  test('09-imports', async ({ page }) => {
    await navigateTo(page, '/metering/imports')
    await page.waitForSelector('.card', { timeout: 10_000 })
    await screenshotFull(page, '09-imports')
  })

  // 10 — Admin Dashboard
  test('10-admin-dashboard', async ({ page }) => {
    await navigateTo(page, '/admin')
    await page.waitForSelector('.card', { timeout: 10_000 })
    await screenshotFull(page, '10-admin-dashboard')
  })

  // 11 — Admin Accounts
  test('11-admin-accounts', async ({ page }) => {
    await navigateTo(page, '/admin/accounts/users')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '11-admin-accounts')
  })

  // 12 — Admin Regional Settings
  test('12-admin-regional-settings', async ({ page }) => {
    await navigateTo(page, '/admin/system-settings?tab=regional')
    await page.waitForSelector('form, .card', { timeout: 10_000 })
    await screenshotFull(page, '12-admin-regional-settings')
  })

  // 13 — Admin VAT Settings (4th tab of System Settings)
  test('13-admin-vat-settings', async ({ page }) => {
    await navigateTo(page, '/admin/system-settings?tab=vat')
    await page.waitForURL('**/admin/system-settings?tab=vat', { timeout: 10_000 })
    await page.waitForSelector('form, table, .card', { timeout: 10_000 })
    await screenshotFull(page, '13-admin-vat-settings')
  })

  // 14 — Admin PDF Templates
  test('14-admin-pdf-templates', async ({ page }) => {
    await navigateTo(page, '/admin/pdf-templates')
    await page.waitForSelector('.card, textarea', { timeout: 10_000 })
    await page.waitForSelector('iframe[title]', { timeout: 15_000 })
    await assertPdfLoaded(page)
    await closePdfSidebar(page)
    await screenshotFull(page, '14-admin-pdf-templates')
  })

  // 14b — Admin Email Templates
  test('14b-admin-email-templates', async ({ page }) => {
    await navigateTo(page, '/admin/email-templates')
    await page.waitForSelector('.card, textarea', { timeout: 10_000 })
    await screenshotFull(page, '14b-admin-email-templates')
  })

  // 15 — Admin ZEV List
  // Only the two demo communities: a developer's own ZEVs on the same stack
  // (real names, real addresses) must never end up in the published guide.
  test('15-admin-zevs', async ({ page }) => {
    await page.route(/\/zev\/zevs\/(\?.*)?$/, async (route) => {
      const response = await route.fetch()
      const body = await response.json() as { results?: Array<{ name: string }>, count?: number } | Array<{ name: string }>
      const demo = (zev: { name: string }) => DEMO_ZEV_NAMES.includes(zev.name)
      const filtered = Array.isArray(body)
        ? body.filter(demo)
        : { ...body, results: body.results?.filter(demo), count: body.results?.filter(demo).length }
      await route.fulfill({ response, json: filtered })
    })
    await navigateTo(page, '/admin/zevs')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '15-admin-zevs')
  })

  // 16 — Account: one capture per tab (the tab lives in ?tab=)
  test('16-account-profile', async ({ page }) => {
    await navigateTo(page, '/account?tab=profile')
    // Panels stay mounted (hidden), so wait for a *visible* card, not the first.
    await page.locator('.card:visible').first().waitFor({ timeout: 10_000 })
    await screenshotFull(page, '16-account-profile')
  })

  test('16b-account-security', async ({ page }) => {
    await navigateTo(page, '/account?tab=security')
    await page.locator('.card:visible').first().waitFor({ timeout: 10_000 })
    await screenshotFull(page, '16b-account-security')
  })

  test('16c-account-api-keys', async ({ page }) => {
    await navigateTo(page, '/account?tab=api-keys')
    await page.locator('.card:visible').first().waitFor({ timeout: 10_000 })
    await screenshotFull(page, '16c-account-api-keys')
  })

  // 17 — Admin Invoices
  test('17-admin-invoices', async ({ page }) => {
    await navigateTo(page, '/admin/invoices')
    await page.waitForSelector('.data-table, .card', { timeout: 10_000 })
    // The card is there while the list still loads; wait for the list itself.
    await expect(page.getByText(/werden geladen|loading/i)).toHaveCount(0, { timeout: 15_000 })
    await screenshotFull(page, '17-admin-invoices')
  })

  // 17b — Admin Dynamic Price Sources
  // The same disabled synthetic source as the dynamic tariff drawer above.
  test('17b-admin-dynamic-sources', async ({ page }) => {
    const source = await requireDemoDynamicSource(page)
    await navigateTo(page, '/admin/dynamic-sources')
    await expect(page.getByRole('row').filter({ hasText: source.label })).toBeVisible()
    await screenshotFull(page, '17b-admin-dynamic-sources')
  })

  // 23 — Reports (owner view on the demo ZEV)
  test('23-reports', async ({ page }) => {
    await navigateTo(page, '/reports')
    // Demo readings belong to this year; the product defaults to the previous year.
    await page.getByRole('combobox', { name: 'Jahr', exact: true }).selectOption(String(new Date().getFullYear()))
    // The annual report aggregates a year of readings; wait for its figures.
    await page.waitForSelector('.kpi-row', { timeout: 30_000 })
    await screenshotFull(page, '23-reports')
  })

  test('23b-participant-annual-statement', async ({ page }) => {
    await impersonateDemoParticipant(page)
    await navigateTo(page, '/me/statement')
    await page.getByRole('combobox', { name: 'Jahr', exact: true }).selectOption(String(new Date().getFullYear()))
    await page.waitForSelector('#yearly-documents-preview iframe[title]', { timeout: 30_000 })
    await assertPdfLoaded(page)
    await closePdfSidebar(page)
    await screenshotFull(page, '23b-participant-annual-statement')
  })
})
