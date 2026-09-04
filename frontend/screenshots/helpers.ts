/**
 * Shared helpers for screenshot capture.
 *
 * Extracted from ``capture.spec.ts`` so the one-off release-note helper
 * (``shot.spec.ts``) logs in, pins the demo ZEV and sizes a capture exactly
 * the way the user-guide shots do — a release note showing a differently
 * framed app than the guide would look like a different product.
 *
 * The capture functions take their output directory from the caller: the
 * user-guide shots are regenerated as the UI moves, while release-note shots
 * are frozen at the version they document, so the two sets never share a home.
 */
import { expect, type Page } from '@playwright/test'
import path from 'path'

export const BASE = process.env.SCREENSHOT_BASE_URL ?? 'http://localhost:8080'
export const API_BASE = process.env.SCREENSHOT_API_URL ?? 'http://localhost:8000/api/v1'
export const USER = process.env.SCREENSHOT_USER ?? 'admin'
export const PASS = process.env.SCREENSHOT_PASSWORD ?? 'admin1234'

/**
 * The only ZEV the seed fills with readings and tariffs. The app's fallback
 * picks an arbitrary managed ZEV when nothing is pinned, and this database
 * carries dozens of empty tenants — so data-dependent captures must pin it.
 */
export const DEMO_ZEV_NAME = 'OpenZEV Demo Community'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Authenticate via the API. The server sets httpOnly cookies; the browser context carries them automatically. */
export async function loginViaAPI(page: Page) {
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
export async function navigateTo(page: Page, urlPath: string) {
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
export async function goToPreviousPeriod(page: Page) {
  await page.locator('button:has(svg[data-icon="arrow-left"])').first().click()
  await page.waitForTimeout(2000)
}

/** Log in as admin and return the bearer access token (used for subsequent direct API calls). */
export async function getAdminToken(page: Page): Promise<string> {
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
export async function resolveDemoZevId(page: Page): Promise<string | null> {
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
export async function pinDemoZev(page: Page): Promise<boolean> {
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
export async function impersonateDemoParticipant(page: Page): Promise<boolean> {
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
export async function resetHover(page: Page) {
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
export async function screenshotFull(page: Page, dir: string, name: string) {
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
    path: path.join(dir, `${name}.png`),
    fullPage: false,
  })
}

/** Take a viewport-only screenshot (no scroll) — for viewport-scoped UI like modals. */
export async function screenshotViewport(page: Page, dir: string, name: string) {
  await resetHover(page)
  await page.screenshot({
    path: path.join(dir, `${name}.png`),
    fullPage: false,
  })
}

/**
 * Fail loudly if the embedded PDF viewer didn't paint — the iframe element
 * exists even when blank, so assert Chromium's PDF-viewer frame appears.
 */
export async function assertPdfPainted(page: Page) {
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
export async function closePdfSidebar(page: Page) {
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
