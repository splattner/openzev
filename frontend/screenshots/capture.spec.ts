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

/** Authenticate via the API. The server sets httpOnly cookies; the browser context carries them automatically. */
async function loginViaAPI(page: Page) {
  const resp = await page.request.post(`${API_BASE}/auth/token/`, {
    data: { username: USER, password: PASS },
  })
  expect(resp.ok(), `Login failed (${resp.status()})`).toBeTruthy()

  // The server sets openzev_access / openzev_refresh httpOnly cookies on the response.
  // page.request shares the browser context's cookie jar, so subsequent navigations
  // will include those cookies automatically — no localStorage injection needed.
  await page.addInitScript(() => {
    // Ensure sidebar is expanded for screenshots
    localStorage.setItem('openzev.sidebarCollapsed', 'false')
  })
}

/** Navigate and wait until the page is fully loaded and idle. */
async function navigateTo(page: Page, urlPath: string) {
  await page.goto(`${BASE}${urlPath}`, { waitUntil: 'networkidle' })
  // Extra settle time for React renders and TanStack Query fetches
  await page.waitForTimeout(1500)
}

/**
 * Step back one billing period.
 *
 * Pages open on the *current* period, which is still in progress and carries no
 * invoices. `seed_demo` bills the previous complete quarter, so the captures
 * that should show real data step back once. Matches the arrow icon rather than
 * the button label, which is translated.
 */
async function goToPreviousPeriod(page: Page) {
  await page.locator('button:has(svg[data-icon="arrow-left"])').first().click()
  await page.waitForTimeout(2000)
}

/** Log in as admin and return the bearer access token (used for subsequent direct API calls). */
async function getAdminToken(page: Page): Promise<string> {
  // We use a separate direct axios-style POST via page.request. simplejwt still
  // returns the token in the body for the obtain-pair view; the CookieJWTAuthentication
  // layer also falls back to the Authorization header, so this is valid for
  // server-to-server calls within the Playwright helper.
  const resp = await page.request.post(`${API_BASE}/auth/token/`, {
    data: { username: USER, password: PASS },
  })
  expect(resp.ok(), `Admin login failed (${resp.status()})`).toBeTruthy()
  // The body contains no tokens (cookie-based login), so read the cookie instead.
  // For direct API calls from Playwright helpers we need a bearer token; re-use
  // the page context's cookie jar which was populated by loginViaAPI.
  // The access cookie value can be read via the context's storage state.
  const cookies = await page.context().cookies()
  const accessCookie = cookies.find(c => c.name === 'openzev_access')
  // If the cookie is missing (first call before loginViaAPI), perform a login now.
  if (accessCookie) return accessCookie.value
  // Fallback: perform login to populate the cookie jar and return the token.
  await loginViaAPI(page)
  const cookies2 = await page.context().cookies()
  const ac = cookies2.find(c => c.name === 'openzev_access')
  expect(ac, 'openzev_access cookie missing after login').toBeTruthy()
  return ac!.value
}

/**
 * Create a fresh unassigned metering point in the first available ZEV and pin
 * the frontend ZEV selection to that same tenant so the screenshot test can
 * reliably open the assign modal regardless of seed data state.
 */
async function prepareUnassignedMeteringPoint(page: Page): Promise<{ meterId: string } | null> {
  const adminToken = await getAdminToken(page)
  const headers = { Authorization: `Bearer ${adminToken}` }

  const zevsResp = await page.request.get(`${API_BASE}/zev/zevs/`, { headers })
  expect(zevsResp.ok(), `Fetching ZEVs failed (${zevsResp.status()})`).toBeTruthy()
  const zevsBody = await zevsResp.json() as { results?: Array<{ id: string }> }
  const zevId = zevsBody.results?.[0]?.id
  if (!zevId) return null

  const meterId = `screenshot-mp-${Date.now()}`
  const createResp = await page.request.post(`${API_BASE}/zev/metering-points/`, {
    headers,
    data: {
      zev: zevId,
      meter_id: meterId,
      meter_type: 'consumption',
      is_active: true,
      location_description: 'Screenshot fixture',
    },
  })
  expect(createResp.ok(), `Creating metering point failed (${createResp.status()})`).toBeTruthy()

  await page.addInitScript((selectedZevId: string) => {
    localStorage.setItem('openzev.selectedZevId', selectedZevId)
  }, zevId)

  return { meterId }
}

/**
 * Impersonate a participant by calling the impersonate endpoint.
 * The server backs up the admin cookies to openzev_admin_access/openzev_admin_refresh
 * and sets new openzev_access/openzev_refresh cookies for the participant — all
 * handled transparently by the browser context's cookie jar.
 */
async function impersonateFirstParticipant(page: Page): Promise<boolean> {
  const adminToken = await getAdminToken(page)
  const headers = { Authorization: `Bearer ${adminToken}` }

  // Fetch the list of users and find one with role "participant"
  const usersResp = await page.request.get(`${API_BASE}/auth/users/`, { headers })
  expect(usersResp.ok(), `Fetching users failed (${usersResp.status()})`).toBeTruthy()
  const usersBody = await usersResp.json() as { results: Array<{ id: number; role: string }> }
  const participant = usersBody.results.find(u => u.role === 'participant')
  if (!participant) return false

  // Call the impersonate endpoint — the server rotates the cookies automatically.
  const impResp = await page.request.post(`${API_BASE}/auth/users/${participant.id}/impersonate/`, { headers })
  expect(impResp.ok(), `Impersonation failed (${impResp.status()})`).toBeTruthy()

  // The app detects impersonation from the JWT claim (impersonated_by) returned by
  // /auth/me/, so no localStorage injection is needed.
  await page.addInitScript(() => {
    localStorage.setItem('openzev.sidebarCollapsed', 'false')
  })

  return true
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
 * - `blurInputs`: CSS selector for `<input>` elements to blur by inline style.
 *
 * Never match on visible text: this suite runs in de-CH, so any English string
 * stops matching the moment a page is translated, and PII silently un-blurs.
 * Target `name` attributes or structural selectors instead.
 */
interface BlurConfig {
  selectors?: string
  blurInputs?: string
}

const PAGE_BLUR: Record<string, BlurConfig> = {
  dashboard: {
    selectors: [
      'section.card > h3',                          // energy balance heading (ZEV + participant name)
      '.inline-form select',                         // participant filter dropdown
      'section.card table tbody td:first-child',     // participant name column in stats table
      '.sankey-participant-label',                   // participant names in Sankey energy flow chart
    ].join(', '),
  },
  'participant-dashboard': {
    selectors: [
      '.impersonation-banner strong',                // impersonation banner name
      '.sankey-participant-label',                   // participant names in Sankey energy flow chart
    ].join(', '),
  },
  participants: {
    selectors: [
      '.participant-card-title strong',              // participant name
      '.participant-card-section:nth-child(1) > div:not(.participant-card-label)', // email + phone
      '.participant-card-section:nth-child(2) > div:not(.participant-card-label)', // address
      'section.card p strong',                       // credentials notice: name
      'code',                                        // credentials notice: username/password
    ].join(', '),
  },
  'metering-points': {
    selectors: [
      '.metering-point-title strong',                // metering point id
      '.metering-assignment-line strong',            // assigned participant name
    ].join(', '),
  },
  'metering-points-modal': {
    selectors: [
      '.metering-point-title strong',                // metering point id
      '.metering-assignment-line strong',            // assigned participant name in background card
      'div[style*="z-index: 1000"] select',          // participant dropdown inside modal
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
    // Match by name attribute, not label text: labels are translated and the
    // suite runs in de-CH, so English label text silently stops matching.
    blurInputs: 'input[name="name"], input[name="bank_name"], input[name="bank_iban"]',
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
  'admin-invoices': {
    selectors: [
      '.MuiDataGrid-cell[data-field="participant_name"]', // participant name
      '.MuiDataGrid-cell[data-field="zev_name"]',         // ZEV name
    ].join(', '),
  },
  'account-profile': {
    selectors: [
      '.form-grid > .card:last-child strong',       // OAuth provider display name
      '.form-grid > .card:last-child button',       // link buttons can include provider name
    ].join(', '),
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

  // 3. Blur specific input elements by CSS selector
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
    await goToPreviousPeriod(page)
    // The energy-flow Sankey only renders once the period has readings.
    await page.waitForSelector('.sankey-participant-label', { timeout: 15_000 })
    await screenshotViewport(page, '02-dashboard', 'dashboard')
  })

  // 02b — Participant Dashboard (via impersonation)
  test('02b-participant-dashboard', async ({ page }) => {
    const ok = await impersonateFirstParticipant(page)
    if (!ok) {
      test.skip()
      return
    }
    await navigateTo(page, '/')
    await page.waitForSelector('.card, .stat-card', { timeout: 10_000 })
    await goToPreviousPeriod(page)
    await page.waitForSelector('.sankey-participant-label', { timeout: 15_000 })
    await screenshotViewport(page, '02b-participant-dashboard', 'participant-dashboard')
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
    const fixture = await prepareUnassignedMeteringPoint(page)
    if (!fixture) {
      test.skip()
      return
    }

    await navigateTo(page, '/metering-points')
    await page.waitForSelector('.metering-point-card, table, .card', { timeout: 10_000 })

    const pointCard = page.locator('.metering-point-card').filter({ hasText: fixture.meterId }).first()
    await expect(pointCard).toBeVisible({ timeout: 10_000 })

    const assignBtn = pointCard.getByRole('button', {
      name: /assign|zuweisen|assigner|assegna/i,
    })
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

  // 07b — A tariff's version history and price chart, both behind the expander
  test('07b-tariff-versions', async ({ page }) => {
    await navigateTo(page, '/tariffs')
    const card = page.locator('article.tariff-card').filter({ hasText: 'Grid Energy HT/NT' }).first()
    await card.waitFor({ timeout: 10_000 })
    // The expander is the only button on the card carrying aria-expanded.
    await card.getByRole('button', { expanded: false }).click()
    // Waiting on the chart rather than the history: it renders only for a series
    // with more than one version, so it also asserts the seed still has them.
    await card.locator('.tariff-price-history').waitFor({ timeout: 10_000 })
    await page.waitForTimeout(1000)  // let Recharts finish laying out
    await screenshot(page, '07b-tariff-versions')
  })

  // 08 — Invoices (period overview)
  test('08-invoices', async ({ page }) => {
    await navigateTo(page, '/invoices')
    await page.waitForSelector('table, .card', { timeout: 10_000 })
    // Invoices are seeded for the last complete period, not the current one.
    await goToPreviousPeriod(page)
    await screenshot(page, '08-invoices', 'invoices')
  })

  // 08b — Invoice Detail page
  test('08b-invoice-detail', async ({ page }) => {
    // Fetch the first existing invoice ID via the API. The login endpoint is
    // cookie-based and returns no token in its body, so read the access cookie
    // via getAdminToken rather than reaching for a `.access` field that has
    // never existed — a bogus header here overrides the valid cookie and 401s.
    const resp = await page.request.get(`${API_BASE}/invoices/invoices/`, {
      headers: { Authorization: `Bearer ${await getAdminToken(page)}` },
    })
    expect(resp.ok(), `Invoice list request failed (${resp.status()})`).toBeTruthy()

    const body = await resp.json() as { results?: Array<{ id: string }> }
    const invoiceId = body.results?.[0]?.id

    // Fail loudly rather than silently capturing the invoices overview under the
    // invoice-detail name, which is how this file came to hold a duplicate.
    expect(invoiceId, 'No invoice found — run `manage.py seed_demo` first').toBeTruthy()

    await navigateTo(page, `/invoices/${invoiceId}`)
    await page.waitForSelector('.grid-4', { timeout: 10_000 })
    await page.waitForTimeout(500)
    await screenshot(page, '08b-invoice-detail', 'invoice-detail')
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

  // 14b — Admin Email Templates
  test('14b-admin-email-templates', async ({ page }) => {
    await navigateTo(page, '/admin/email-templates')
    await page.waitForSelector('.card, textarea', { timeout: 10_000 })
    await screenshot(page, '14b-admin-email-templates')
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

  // 17 — Admin Invoices
  test('17-admin-invoices', async ({ page }) => {
    await navigateTo(page, '/admin/invoices')
    await page.waitForSelector('.MuiDataGrid-root, .card', { timeout: 10_000 })
    await screenshot(page, '17-admin-invoices', 'admin-invoices')
  })
})
