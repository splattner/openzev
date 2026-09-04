/**
 * Automated screenshot generation for user-guide documentation.
 *
 * Run:
 *   cd frontend
 *   npx playwright test --config screenshots.config.ts
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
import {
  assertPdfPainted,
  closePdfSidebar,
  getAdminToken,
  goToPreviousPeriod,
  impersonateDemoParticipant,
  loginViaAPI,
  navigateTo,
  pinDemoZev,
  screenshotFull as captureFull,
  screenshotViewport as captureViewport,
  API_BASE,
} from './helpers'


/**
 * The only ZEV the seed fills with readings and tariffs. The app's fallback
 * picks an arbitrary managed ZEV when nothing is pinned, and this database
 * carries dozens of empty tenants — so data-dependent captures must pin it.
 */

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const SCREENSHOT_DIR = path.resolve(__dirname, '../../docs/user-guide/screenshots')

const screenshotFull = (page: Page, name: string) => captureFull(page, SCREENSHOT_DIR, name)
const screenshotViewport = (page: Page, name: string) => captureViewport(page, SCREENSHOT_DIR, name)

// ---------------------------------------------------------------------------
// Screenshot tests — one test per page / state
// ---------------------------------------------------------------------------

test.describe('User Guide Screenshots', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaAPI(page)
  })

  // 01 — Login page (unauthenticated)
  test('01-login', async ({ page }) => {
    await navigateTo(page, '/login')
    await page.waitForSelector('form')
    await screenshotFull(page, '01-login')
  })

  // 02 — Dashboard
  test('02-dashboard', async ({ page }) => {
    if (!(await pinDemoZev(page))) {
      test.skip()
      return
    }
    await navigateTo(page, '/')
    // Wait for dashboard content (stat cards or similar)
    await page.waitForSelector('.card', { timeout: 10_000 })
    await goToPreviousPeriod(page)
    // The energy-flow Sankey only renders once the period has readings.
    await page.waitForSelector('.sankey-participant-label', { timeout: 15_000 })
    await screenshotFull(page, '02-dashboard')
  })

  // 02b — Participant Dashboard (via impersonation)
  test('02b-participant-dashboard', async ({ page }) => {
    const ok = await impersonateDemoParticipant(page)
    if (!ok) {
      test.skip()
      return
    }
    await navigateTo(page, '/')
    await page.waitForSelector('.card, .stat-card', { timeout: 10_000 })
    await goToPreviousPeriod(page)
    await page.waitForSelector('.sankey-participant-label', { timeout: 15_000 })
    await screenshotFull(page, '02b-participant-dashboard')
  })

  // 03 — Participants
  test('03-participants', async ({ page }) => {
    await navigateTo(page, '/participants')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '03-participants')
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
    if (!(await pinDemoZev(page))) {
      test.skip()
      return
    }

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
    if (!(await pinDemoZev(page))) {
      test.skip()
      return
    }
    await navigateTo(page, '/metering-data')
    await page.waitForSelector('.card', { timeout: 10_000 })
    // Select the first metering point that can carry readings.
    const mpSelect = page.locator('select').first()
    const options = mpSelect.locator('option')
    const count = await options.count()
    for (let i = 1; i < count; i++) {
      const label = await options.nth(i).textContent()
      const value = await options.nth(i).getAttribute('value')
      if (value && label) {
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

  // 07 — Tariffs
  test('07-tariffs', async ({ page }) => {
    await navigateTo(page, '/tariffs')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '07-tariffs')
  })

  // 07b — A tariff's version history and price chart, both behind the expander
  test('07b-tariff-versions', async ({ page }) => {
    if (!(await pinDemoZev(page))) {
      test.skip()
      return
    }
    await navigateTo(page, '/tariffs')
    const card = page.locator('article.tariff-card').filter({ hasText: 'Grid Energy HT/NT' }).first()
    await card.waitFor({ timeout: 10_000 })
    // The expander is the only button on the card carrying aria-expanded.
    await card.getByRole('button', { expanded: false }).click()
    // Waiting on the chart rather than the history: it renders only for a series
    // with more than one version, so it also asserts the seed still has them.
    await card.locator('.tariff-price-history').waitFor({ timeout: 10_000 })
    await page.waitForTimeout(1000)  // let Recharts finish laying out
    await screenshotFull(page, '07b-tariff-versions')
  })

  // 08 — Invoices (period overview)
  test('08-invoices', async ({ page }) => {
    await navigateTo(page, '/invoices')
    await page.waitForSelector('.period-selector', { timeout: 10_000 })
    // The page opens on the last complete period — exactly where seed_demo
    // bills — so no period navigation here (see goToPreviousPeriod docstring).
    await screenshotFull(page, '08-invoices')
  })

  // 08b — Invoice Detail page
  test('08b-invoice-detail', async ({ page }) => {
    const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
    const resp = await page.request.get(`${API_BASE}/invoices/invoices/`, { headers })
    expect(resp.ok(), `Invoice list request failed (${resp.status()})`).toBeTruthy()

    const body = await resp.json() as { results?: Array<{ id: string; pdf_url: string | null }> }
    const invoice = body.results?.[0]

    // Fail loudly rather than silently capturing the invoices overview under the
    // invoice-detail name, which is how this file came to hold a duplicate.
    expect(invoice, 'No invoice found — run `manage.py seed_demo` first').toBeTruthy()

    // Reseeding the database wipes stored PDF artifacts, so the embed would
    // show the "generate" card instead of a document. Generate one up front.
    if (!invoice!.pdf_url) {
      const gen = await page.request.post(`${API_BASE}/invoices/invoices/${invoice!.id}/generate-pdf/`, { headers })
      expect(gen.ok(), `PDF generation failed (${gen.status()})`).toBeTruthy()
    }

    // screenshotFull grows the viewport to the content height, so the embedded
    // PDF viewer — which Chromium only paints inside the viewport — renders.
    await navigateTo(page, `/invoices/${invoice!.id}`)
    await page.waitForSelector('.grid-4', { timeout: 10_000 })
    await page.waitForSelector('iframe[title]', { timeout: 15_000 })
    await page.waitForTimeout(3500)
    await assertPdfPainted(page)
    await closePdfSidebar(page)
    await screenshotFull(page, '08b-invoice-detail')
  })

  // 09 — Imports
  test('09-imports', async ({ page }) => {
    await navigateTo(page, '/imports')
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
    await navigateTo(page, '/admin/accounts')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '11-admin-accounts')
  })

  // 12 — Admin Regional Settings
  test('12-admin-regional-settings', async ({ page }) => {
    await navigateTo(page, '/admin/settings/regional')
    await page.waitForSelector('form, .card', { timeout: 10_000 })
    await screenshotFull(page, '12-admin-regional-settings')
  })

  // 13 — Admin VAT Settings (4th tab of System Settings; legacy URL redirects to it)
  test('13-admin-vat-settings', async ({ page }) => {
    await navigateTo(page, '/admin/settings/vat')
    await page.waitForURL('**/admin/system-settings?tab=vat', { timeout: 10_000 })
    await page.waitForSelector('form, table, .card', { timeout: 10_000 })
    await screenshotFull(page, '13-admin-vat-settings')
  })

  // 14 — Admin PDF Templates
  test('14-admin-pdf-templates', async ({ page }) => {
    await navigateTo(page, '/admin/pdf-templates')
    await page.waitForSelector('.card, textarea', { timeout: 10_000 })
    await page.waitForSelector('iframe[title]', { timeout: 15_000 })
    await page.waitForTimeout(1000)
    await assertPdfPainted(page)
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
  test('15-admin-zevs', async ({ page }) => {
    await navigateTo(page, '/admin/zevs')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshotFull(page, '15-admin-zevs')
  })

  // 16 — Account Profile
  test('16-account-profile', async ({ page }) => {
    await navigateTo(page, '/account')
    await page.waitForSelector('form, .card', { timeout: 10_000 })
    await screenshotFull(page, '16-account-profile')
  })

  // 17 — Admin Invoices
  test('17-admin-invoices', async ({ page }) => {
    await navigateTo(page, '/admin/invoices')
    await page.waitForSelector('.data-table, .card', { timeout: 10_000 })
    await screenshotFull(page, '17-admin-invoices')
  })

  // 23 — Reports (owner view on the demo ZEV)
  test('23-reports', async ({ page }) => {
    if (!(await pinDemoZev(page))) {
      test.skip()
      return
    }
    await navigateTo(page, '/reports')
    await page.waitForSelector('.card', { timeout: 10_000 })
    await screenshotFull(page, '23-reports')
  })
})
