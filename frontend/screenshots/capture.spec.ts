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

const BASE = process.env.SCREENSHOT_BASE_URL ?? 'http://localhost:8080'
const API_BASE = process.env.SCREENSHOT_API_URL ?? 'http://localhost:8000/api/v1'
const USER = process.env.SCREENSHOT_USER ?? 'admin'
const PASS = process.env.SCREENSHOT_PASSWORD ?? 'admin1234'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const SCREENSHOT_DIR = path.resolve(__dirname, '../../docs/user-guide/screenshots')

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Authenticate via the API and inject tokens into localStorage. */
async function loginViaAPI(page: Page) {
  const resp = await page.request.post(`${API_BASE}/auth/token/`, {
    data: { username: USER, password: PASS },
  })
  expect(resp.ok(), `Login failed (${resp.status()})`).toBeTruthy()
  const tokens = await resp.json() as { access: string; refresh: string }

  // Inject tokens into localStorage before any navigation.
  await page.addInitScript((t) => {
    localStorage.setItem('openzev.access', t.access)
    localStorage.setItem('openzev.refresh', t.refresh)
    // Ensure sidebar is expanded for screenshots
    localStorage.setItem('openzev.sidebarCollapsed', 'false')
  }, tokens)
}

/** Navigate and wait until the page is fully loaded and idle. */
async function navigateTo(page: Page, urlPath: string) {
  await page.goto(`${BASE}${urlPath}`, { waitUntil: 'networkidle' })
  // Extra settle time for React renders and TanStack Query fetches
  await page.waitForTimeout(1500)
}

// ---------------------------------------------------------------------------
// PII blurring — page-specific CSS + JS to redact sensitive information
// ---------------------------------------------------------------------------

/** Global PII selectors — applied on every authenticated page (header/nav) */
const GLOBAL_PII_CSS = `
  .user-menu .user-meta strong,
  .user-menu .user-meta small,
  .zev-menu .user-meta small,
  .impersonation-banner strong {
    filter: blur(6px) !important;
    -webkit-filter: blur(6px) !important;
    user-select: none !important;
  }
`

/**
 * Per-page blur configuration.
 * - `selectors`: CSS selectors whose matched elements get `filter: blur(6px)`.
 * - `blurLabels`: Label `<span>` text identifying form inputs to blur by value.
 * - `blurInputs`: CSS selector for `<input>` elements to blur by inline style.
 */
interface BlurConfig {
  selectors?: string
  blurLabels?: string[]
  blurInputs?: string
}

const PAGE_BLUR: Record<string, BlurConfig> = {
  dashboard: {
    selectors: [
      'section.card > h3',                          // energy balance heading (ZEV + participant name)
      '.inline-form select',                         // participant filter dropdown
      'section.card table tbody td:first-child',     // participant name column in stats table
    ].join(', '),
  },
  participants: {
    selectors: [
      '.table-card table tbody td:nth-child(1)',     // participant name
      '.table-card table tbody td:nth-child(2)',     // email + phone
      '.table-card table tbody td:nth-child(3)',     // address
      'section.card p strong',                       // credentials notice: name
      'code',                                        // credentials notice: username/password
    ].join(', '),
  },
  'metering-points': {
    selectors: '.table-card table tbody td:first-child', // participant name in assignment sub-table
  },
  'metering-points-modal': {
    selectors: [
      '.table-card table tbody td:first-child',      // participant name in assignment sub-table
      'div[style*="z-index: 1000"] select',           // participant dropdown inside modal
    ].join(', '),
  },
  invoices: {
    selectors: [
      'div[style*="font-weight"]',                   // ZEV name in period navigation card
      '.table-card table tbody td:first-child',      // participant name + email column
    ].join(', '),
  },
  'invoice-detail': {
    selectors: [
      '.page-stack > header p.muted',                // participant name + period in subtitle
    ].join(', '),
  },
  'zev-settings': {
    blurLabels: ['Name', 'Bank name', 'Bank IBAN'],  // sensitive form fields only
  },
  'admin-accounts': {
    selectors: [
      '.table-card table tbody td:nth-child(2)',     // participant name + email
      '.table-card table tbody td:nth-child(3)',     // ZEV name
      '.table-card table tbody td:nth-child(4)',     // account username + email
      'section.card p strong',                       // credentials notice: name
      'code',                                        // credentials notice: username/password
    ].join(', '),
  },
  'admin-zevs': {
    selectors: [
      '.table-card table tbody td:nth-child(1)',     // ZEV name
      '.table-card table tbody td:nth-child(2)',     // owner name
    ].join(', '),
  },
  'account-profile': {
    blurInputs: 'input[name="first_name"], input[name="last_name"], input[name="email"], input[disabled]',
  },
}

/**
 * Apply PII blur — global header selectors + page-specific rules.
 * Call AFTER the page has loaded but BEFORE taking the screenshot.
 */
async function blurPII(page: Page, pageKey?: string) {
  // 1. Global header blur (always)
  await page.addStyleTag({ content: GLOBAL_PII_CSS })

  // 2. Page-specific element blur via CSS
  const config = pageKey ? PAGE_BLUR[pageKey] : undefined

  if (config?.selectors) {
    await page.addStyleTag({
      content: `${config.selectors} { filter: blur(6px) !important; -webkit-filter: blur(6px) !important; user-select: none !important; }`,
    })
  }

  // 3. Blur form inputs identified by their associated label text
  if (config?.blurLabels?.length) {
    await page.evaluate((labels: string[]) => {
      for (const label of document.querySelectorAll('label')) {
        const span = label.querySelector('span')
        if (span && labels.includes(span.textContent?.trim() ?? '')) {
          const input = label.querySelector('input, textarea, select') as HTMLElement | null
          if (input) input.style.filter = 'blur(6px)'
        }
      }
    }, config.blurLabels)
  }

  // 4. Blur specific input elements by CSS selector
  if (config?.blurInputs) {
    await page.evaluate((selector: string) => {
      for (const el of document.querySelectorAll<HTMLInputElement>(selector)) {
        if (el.value?.trim()) el.style.filter = 'blur(6px)'
      }
    }, config.blurInputs)
  }

  // Brief settle after DOM changes
  await page.waitForTimeout(200)
}

/** Take a full-page screenshot with PII blurred. */
async function screenshot(page: Page, name: string, pageKey?: string) {
  await blurPII(page, pageKey)
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: true,
  })
}

/** Take a viewport-only screenshot (no scroll) with PII blurred. */
async function screenshotViewport(page: Page, name: string, pageKey?: string) {
  await blurPII(page, pageKey)
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: false,
  })
}

// ---------------------------------------------------------------------------
// Screenshot tests — one test per page / state
// ---------------------------------------------------------------------------

test.describe('User Guide Screenshots', () => {
  test.beforeEach(async ({ page }) => {
    await loginViaAPI(page)
  })

  // 01 — Login page (unauthenticated)
  test('01-login', async ({ page }) => {
    // Clear tokens so we see the login page
    await page.addInitScript(() => {
      localStorage.removeItem('openzev.access')
      localStorage.removeItem('openzev.refresh')
    })
    await navigateTo(page, '/login')
    await page.waitForSelector('form')
    await screenshot(page, '01-login')
  })

  // 02 — Dashboard
  test('02-dashboard', async ({ page }) => {
    await navigateTo(page, '/')
    // Wait for dashboard content (stat cards or similar)
    await page.waitForSelector('.card', { timeout: 10_000 })
    await screenshotViewport(page, '02-dashboard', 'dashboard')
  })

  // 03 — Participants
  test('03-participants', async ({ page }) => {
    await navigateTo(page, '/participants')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshot(page, '03-participants', 'participants')
  })

  // 04 — Metering Points
  test('04-metering-points', async ({ page }) => {
    await navigateTo(page, '/metering-points')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshot(page, '04-metering-points', 'metering-points')
  })

  // 04b — Metering Points with Assign Participant modal
  test('04b-metering-points-assign', async ({ page }) => {
    await navigateTo(page, '/metering-points')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    // Click the first "+ Zuweisen" / "+ Assign" button
    const assignBtn = page.locator('button').filter({ hasText: /Zuweisen|Assign/ }).first()
    await assignBtn.click()
    // Wait for modal overlay to appear
    await page.waitForSelector('div[style*="z-index: 1000"]', { timeout: 5_000 })
    await page.waitForTimeout(500)
    await screenshotViewport(page, '04b-metering-points-assign', 'metering-points-modal')
  })

  // 05 — Metering Data / Charts (with a metering point selected)
  test('05-metering-data', async ({ page }) => {
    await navigateTo(page, '/metering-data')
    await page.waitForSelector('.card', { timeout: 10_000 })
    // Select the first available metering point to show chart data
    const mpSelect = page.locator('select').first()
    const options = mpSelect.locator('option')
    const count = await options.count()
    if (count > 1) {
      // Pick the second option (first is the placeholder)
      const value = await options.nth(1).getAttribute('value')
      if (value) {
        await mpSelect.selectOption(value)
        // Wait for chart to render
        await page.waitForSelector('.recharts-wrapper', { timeout: 15_000 })
        await page.waitForTimeout(1000)
      }
    }
    await screenshotViewport(page, '05-metering-data')
  })

  // 06 — ZEV Settings
  test('06-zev-settings', async ({ page }) => {
    await navigateTo(page, '/zev-settings')
    await page.waitForSelector('form, .card', { timeout: 10_000 })
    await screenshot(page, '06-zev-settings', 'zev-settings')
  })

  // 07 — Tariffs
  test('07-tariffs', async ({ page }) => {
    await navigateTo(page, '/tariffs')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshot(page, '07-tariffs')
  })

  // 08 — Invoices (period overview)
  test('08-invoices', async ({ page }) => {
    await navigateTo(page, '/invoices')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshot(page, '08-invoices', 'invoices')
  })

  // 08b — Invoice Detail page
  test('08b-invoice-detail', async ({ page }) => {
    // Fetch the first existing invoice ID via the API
    const resp = await page.request.get(`${API_BASE}/invoices/invoices/`, {
      headers: {
        Authorization: `Bearer ${(await page.request.post(`${API_BASE}/auth/token/`, {
          data: { username: USER, password: PASS },
        }).then((r) => r.json()) as { access: string }).access}`,
      },
    })
    const body = await resp.json() as { results?: Array<{ id: string }> }
    const invoiceId = body.results?.[0]?.id

    if (invoiceId) {
      await navigateTo(page, `/invoices/${invoiceId}`)
      await page.waitForSelector('.grid-4', { timeout: 10_000 })
      await page.waitForTimeout(500)
      await screenshot(page, '08b-invoice-detail', 'invoice-detail')
    } else {
      // No invoices exist — take the invoices overview as fallback
      await navigateTo(page, '/invoices')
      await page.waitForSelector('table, .card', { timeout: 10_000 })
      await screenshot(page, '08b-invoice-detail', 'invoices')
    }
  })

  // 09 — Imports
  test('09-imports', async ({ page }) => {
    await navigateTo(page, '/imports')
    await page.waitForSelector('.card', { timeout: 10_000 })
    await screenshot(page, '09-imports')
  })

  // 10 — Admin Dashboard
  test('10-admin-dashboard', async ({ page }) => {
    await navigateTo(page, '/admin')
    await page.waitForSelector('.card', { timeout: 10_000 })
    await screenshotViewport(page, '10-admin-dashboard')
  })

  // 11 — Admin Accounts
  test('11-admin-accounts', async ({ page }) => {
    await navigateTo(page, '/admin/accounts')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshot(page, '11-admin-accounts', 'admin-accounts')
  })

  // 12 — Admin Regional Settings
  test('12-admin-regional-settings', async ({ page }) => {
    await navigateTo(page, '/admin/settings/regional')
    await page.waitForSelector('form, .card', { timeout: 10_000 })
    await screenshot(page, '12-admin-regional-settings')
  })

  // 13 — Admin VAT Settings
  test('13-admin-vat-settings', async ({ page }) => {
    await navigateTo(page, '/admin/settings/vat')
    await page.waitForSelector('form, table, .card', { timeout: 10_000 })
    await screenshot(page, '13-admin-vat-settings')
  })

  // 14 — Admin PDF Templates
  test('14-admin-pdf-templates', async ({ page }) => {
    await navigateTo(page, '/admin/pdf-templates')
    await page.waitForSelector('.card, textarea', { timeout: 10_000 })
    await screenshot(page, '14-admin-pdf-templates')
  })

  // 15 — Admin ZEV List
  test('15-admin-zevs', async ({ page }) => {
    await navigateTo(page, '/admin/zevs')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    await screenshot(page, '15-admin-zevs', 'admin-zevs')
  })

  // 16 — Account Profile
  test('16-account-profile', async ({ page }) => {
    await navigateTo(page, '/account')
    await page.waitForSelector('form, .card', { timeout: 10_000 })
    await screenshot(page, '16-account-profile', 'account-profile')
  })
})
