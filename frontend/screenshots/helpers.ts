/** Shared helpers for screenshot capture (user-guide + one-off release-note shots). */
import { expect, type Page } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'

export const BASE = process.env.SCREENSHOT_BASE_URL ?? 'http://localhost:8080'
// The default compose stack reaches the API same-origin through nginx; the dev
// stack publishes the backend directly (override with SCREENSHOT_API_URL).
export const API_BASE = process.env.SCREENSHOT_API_URL ?? 'http://localhost:8080/api/v1'
export const USER = process.env.SCREENSHOT_USER ?? 'admin@openzev.local'
export const PASS = process.env.SCREENSHOT_PASSWORD ?? 'admin1234'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

/**
 * Where the setup project persists the admin's authenticated storage state
 * (see auth.setup.ts). Gitignored: it holds a live session cookie.
 */
export const AUTH_STATE_PATH = path.join(__dirname, '.auth', 'admin.json')

/**
 * Pin Sonnenhof so screenshots consistently show the same community: both
 * demo ZEVs carry data, and a capture that drifted onto the second community
 * would silently change frame. The flagship id is resolved by name and stored
 * as the browser's selection before any navigation, so database collation
 * cannot move the capture either.
 */
export const DEMO_ZEV_NAME = 'ZEV STWEG Sonnenhof'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

/**
 * Return a bearer access token for direct API calls from Playwright helpers.
 *
 * The token is the `openzev_access` cookie set by the login endpoint, and the
 * suite authenticates each context via the setup project's storage state — so
 * in the common case this only reads the cookie jar. Only when the cookie is
 * missing (a context that skipped the shared auth state) do we log in here.
 * Every avoidable POST counts: the backend throttles `auth/token/` per IP at
 * 40/hour, and all captures share one IP.
 */
export async function getAdminToken(page: Page): Promise<string> {
  // CookieJWTAuthentication also accepts the value as an Authorization bearer
  // header, so the cookie value doubles as the token for direct API calls.
  const readCookie = async () =>
    (await page.context().cookies(API_BASE)).find(c => c.name === 'openzev_access')?.value
  const existing = await readCookie()
  if (existing) return existing

  const resp = await page.request.post(`${API_BASE}/auth/token/`, {
    data: { email: USER, password: PASS },
  })
  expect(resp.ok(), `Admin login failed (${resp.status()})`).toBeTruthy()
  const token = await readCookie()
  expect(token, 'openzev_access cookie missing after login').toBeTruthy()
  return token!
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
 *
 * The selection is a server-side account preference (User.preferred_zev), so
 * persist it via PATCH /auth/me/ with the admin token.
 */
export async function pinDemoZev(page: Page): Promise<boolean> {
  const zevId = await resolveDemoZevId(page)
  if (!zevId) return false
  const adminToken = await getAdminToken(page)
  const resp = await page.request.patch(`${API_BASE}/auth/me/`, {
    headers: { Authorization: `Bearer ${adminToken}` },
    data: { preferred_zev: zevId },
  })
  expect(resp.ok(), `Saving preferred ZEV failed (${resp.status()})`).toBeTruthy()
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

const SHOT_WIDTH = 1440
const BASE_HEIGHT = 900
const MAX_SLOPE = 0.9
const MAX_MEASURE_STEPS = 4
const SETTLE_MS = 400

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
 *
 * Tables stay uncapped through the capture (see below); a slope above
 * MAX_SLOPE fails loudly instead of committing a half-blank capture.
 */
export async function screenshotFull(page: Page, dir: string, name: string) {
  // Visible ones only: a hidden, kept-mounted tab panel (the account page) may
  // hold placeholders for content that only loads once its tab is shown.
  await expect(page.locator('.skeleton-block:visible')).toHaveCount(0, { timeout: 30_000 })
  await resetHover(page)
  const measure = () => page.evaluate(() => document.documentElement.scrollHeight)
  const resize = async (height: number) => {
    await page.setViewportSize({ width: SHOT_WIDTH, height })
    await page.waitForTimeout(SETTLE_MS)
  }

  await resize(BASE_HEIGHT)
  // Uncap viewport-relative tables while measuring and capturing: the shipped
  // `.table-scroll` cap is 100dvh-relative and would feed a ~1:1 slope into
  // the solver. Where the cap would not bind, pixels match shipped CSS.
  const styleHandle = await page.addStyleTag({
    content: '.table-scroll { max-height: none !important; }',
  })

  let viewport = BASE_HEIGHT
  try {
    let content = await measure()
    let prevViewport: number | null = null
    let prevContent: number | null = null

    for (let i = 0; i < MAX_MEASURE_STEPS && content > viewport; i++) {
      let target = Math.max(BASE_HEIGHT, content)
      if (prevViewport != null && prevContent != null) {
        // Target exceeded the viewport, so the divisor is non-zero.
        const slope = (content - prevContent) / (viewport - prevViewport)
        if (slope > MAX_SLOPE) {
          throw new Error(
            `screenshotFull(${name}): content tracks viewport (slope ${slope.toFixed(2)}; ` +
            `viewport ${prevViewport}→${viewport}, content ${prevContent}→${content})`,
          )
        }
        target = Math.max(BASE_HEIGHT, Math.round((content - slope * viewport) / (1 - slope)))
      }
      prevViewport = viewport
      prevContent = content
      viewport = target
      await resize(viewport)
      content = await measure()
    }
    if (content > viewport) {
      viewport = content
      await resize(viewport)
    }
    await page.screenshot({
      path: path.join(dir, `${name}.png`),
      fullPage: false,
    })
  } finally {
    await styleHandle.evaluate((el) => el.remove()).catch(() => {})
  }
}

/** Take a viewport-only screenshot (no scroll) — for viewport-scoped UI like modals. */
export async function screenshotViewport(page: Page, dir: string, name: string) {
  // Visible ones only: a hidden, kept-mounted tab panel (the account page) may
  // hold placeholders for content that only loads once its tab is shown.
  await expect(page.locator('.skeleton-block:visible')).toHaveCount(0, { timeout: 30_000 })
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
