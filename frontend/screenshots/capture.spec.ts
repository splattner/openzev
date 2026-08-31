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

/**
 * The only ZEV the seed fills with readings and tariffs. The app's fallback
 * picks an arbitrary managed ZEV when nothing is pinned, and this database
 * carries dozens of empty tenants — so data-dependent captures must pin it.
 */
const DEMO_ZEV_NAME = 'OpenZEV Demo Community'

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
 * Dashboard and chart pages open on the *current* period; `seed_demo` fills the
 * last complete quarter, so those captures step back once. Matches the arrow
 * icon rather than the button label, which is translated. The invoices overview
 * must NOT use this: it already opens on the last complete period by design
 * (InvoicesPage), so stepping back would land on an empty one.
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

/** Resolve the id of the data-bearing demo ZEV via the admin API. */
async function resolveDemoZevId(page: Page): Promise<string | null> {
  const adminToken = await getAdminToken(page)
  const zevsResp = await page.request.get(`${API_BASE}/zev/zevs/`, {
    headers: { Authorization: `Bearer ${adminToken}` },
  })
  expect(zevsResp.ok(), `Fetching ZEVs failed (${zevsResp.status()})`).toBeTruthy()
  const zevsBody = await zevsResp.json() as { results?: Array<{ id: string; name: string }> }
  return zevsBody.results?.find(z => z.name === DEMO_ZEV_NAME)?.id ?? null
}

/**
 * Pin the global ZEV selection to the demo ZEV before any navigation so the
 * dashboard, metering charts, tariff and assign-modal captures render seeded
 * data instead of an arbitrary empty tenant.
 */
async function pinDemoZev(page: Page): Promise<boolean> {
  const zevId = await resolveDemoZevId(page)
  if (!zevId) return false
  await page.addInitScript((selectedZevId: string) => {
    localStorage.setItem('openzev.selectedZevId', selectedZevId)
  }, zevId)
  return true
}

/**
 * Impersonate a participant of the demo ZEV. Impersonating the first
 * participant overall would land on whichever empty tenant sorts first and the
 * participant dashboard would render without any readings.
 */
async function impersonateDemoParticipant(page: Page): Promise<boolean> {
  const adminToken = await getAdminToken(page)
  const headers = { Authorization: `Bearer ${adminToken}` }

  const zevId = await resolveDemoZevId(page)
  if (!zevId) return false

  // User ids linked to participants of the demo ZEV.
  const partsResp = await page.request.get(`${API_BASE}/zev/participants/?zev_id=${zevId}`, { headers })
  expect(partsResp.ok(), `Fetching participants failed (${partsResp.status()})`).toBeTruthy()
  const partsBody = await partsResp.json() as { results?: Array<{ user: number | null }> }
  const demoUserIds = new Set((partsBody.results ?? []).map(p => p.user).filter((u): u is number => u != null))
  if (demoUserIds.size === 0) return false

  const usersResp = await page.request.get(`${API_BASE}/auth/users/`, { headers })
  expect(usersResp.ok(), `Fetching users failed (${usersResp.status()})`).toBeTruthy()
  const usersBody = await usersResp.json() as { results: Array<{ id: number; role: string }> }
  const participant = usersBody.results.find(u => u.role === 'participant' && demoUserIds.has(u.id))
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

/** Move the mouse off any element so no hover state leaks into the shot. */
async function resetHover(page: Page) {
  await page.mouse.move(0, 0)
  // Let CSS hover transitions fade out before the capture.
  await page.waitForTimeout(250)
}

/**
 * Capture the whole page by growing the viewport to the content height.
 *
 * `fullPage: true` is not usable here: it captures beyond the viewport without
 * re-resolving `100dvh`, so the sticky sidebar stops at the original viewport
 * height while the main column continues, and Chromium's PDF plugin (which
 * only paints surfaces inside the viewport) leaves embedded PDF viewers blank.
 * Resizing first fixes both, because every surface ends up inside the viewport.
 *
 * Content height can itself depend on viewport height (the PDF embeds are
 * 70–72vh), so after growing, re-measure; if the target moved, solve the
 * linear model c(h) = base + factor·h from both samples and jump straight to
 * its fixed point c(h) = h instead of creeping toward it.
 */
async function screenshotFull(page: Page, name: string) {
  await resetHover(page)
  const measure = () => page.evaluate(() => document.documentElement.scrollHeight)
  const resize = async (height: number) => {
    await page.setViewportSize({ width: 1440, height })
    await page.waitForTimeout(400)
  }

  let viewport = 900
  let content = await measure()
  let prevViewport: number | null = null
  let prevContent: number | null = null

  for (let i = 0; i < 4 && content > viewport; i++) {
    let target = Math.max(900, content)
    if (prevViewport != null && prevContent != null && viewport > prevViewport) {
      const factor = Math.min(0.9, (content - prevContent) / (viewport - prevViewport))
      target = Math.max(900, Math.round((content - factor * viewport) / (1 - factor)))
    }
    prevViewport = viewport
    prevContent = content
    viewport = target
    await resize(viewport)
    content = await measure()
  }
  if (content > viewport) {
    await resize(content) // non-linear fallback: fit whatever grew last
  }
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: false,
  })
}

/** Take a viewport-only screenshot (no scroll) — for viewport-scoped UI like modals. */
async function screenshotViewport(page: Page, name: string) {
  await resetHover(page)
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, `${name}.png`),
    fullPage: false,
  })
}

/**
 * Fail loudly if the embedded PDF viewer didn't paint — the iframe element
 * exists even when blank, so assert Chromium's PDF-viewer frame appears.
 */
async function assertPdfPainted(page: Page) {
  await expect
    .poll(
      () => page.frames().some(f => f.url().startsWith('chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai')),
      {
        message: 'PDF viewer did not paint — re-run with SCREENSHOT_CHANNEL=chromium (default in screenshots.config.ts)',
        timeout: 15_000,
      }
    )
    .toBe(true)
}

/**
 * Close the viewer's thumbnail sidebar: Chromium opens it by default and
 * `#navpanes=0` doesn't reach the viewer on blob URLs, so click the toolbar
 * toggle (`#sidenavToggle`, via `aria-expanded`) instead.
 */
async function closePdfSidebar(page: Page) {
  const viewer = page.frames().find(f => f.url().startsWith('chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai'))
  if (!viewer) return
  const toggle = viewer.locator('#sidenavToggle')
  if (!(await toggle.count())) return
  const wasExpanded = await viewer.evaluate(() => {
    const btn = document.querySelector('pdf-viewer')?.shadowRoot
      ?.querySelector('viewer-toolbar')?.shadowRoot?.querySelector('#sidenavToggle') as HTMLElement | null
    if (!btn) return null
    const expanded = btn.getAttribute('aria-expanded')
    if (expanded === 'true') btn.click()
    return expanded
  })
  if (wasExpanded !== 'true') return // already closed, or no toggle
  // Wait until it actually closed; fail loudly if a Chromium update renames
  // the toggle, instead of committing a screenshot with the strip back.
  await expect
    .poll(
      () => viewer.evaluate(() =>
        document.querySelector('pdf-viewer')?.shadowRoot
          ?.querySelector('viewer-toolbar')?.shadowRoot
          ?.querySelector('#sidenavToggle')?.getAttribute('aria-expanded') ?? 'missing'
      ),
      {
        message: 'PDF viewer sidebar did not close — Chromium viewer DOM changed?',
        timeout: 5_000,
      }
    )
    .toBe('false')
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
