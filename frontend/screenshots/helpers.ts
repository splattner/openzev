/** Shared helpers for screenshot capture (user-guide + one-off release-note shots). */
import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { writeFile } from 'fs/promises'
import path from 'path'
import sharp from 'sharp'
import { fileURLToPath } from 'url'
import type { User } from '../src/types/api'

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

/** The price change capture.setup.ts schedules for the tariff captures, and the note capture.teardown.ts removes it by. */
export const SCHEDULED_CHANGE_FILE = path.join(__dirname, '.auth', 'scheduled-change.json')
export const SCHEDULED_TARIFF = 'Grid Energy HT/NT'

/**
 * Pin Sonnenhof so screenshots consistently show the same community: both
 * demo ZEVs carry data, and a capture that drifted onto the second community
 * would silently change frame. The flagship id is resolved by name and stored
 * as the browser's selection before any navigation, so database collation
 * cannot move the capture either.
 */
export const DEMO_ZEV_NAME = 'ZEV STWEG Sonnenhof'
export const SECOND_DEMO_ZEV_NAME = 'ZEV Sonnenfirma AG'
export const MISSING_DEMO_ZEV = 'Demo ZEV not found — run seed_demo before capturing screenshots'

/** Seeded participant the participant-side captures show. */
const DEMO_PARTICIPANT_EMAIL = 'anna@openzev.local'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Navigate, then wait for network idle, webfonts and no visible loading placeholder. */
export async function navigateTo(page: Page, urlPath: string) {
  await page.goto(`${BASE}${urlPath}`, { waitUntil: 'networkidle' })
  await page.evaluate(() => document.fonts.ready)
  await expect(page.locator('.skeleton-block:visible')).toHaveCount(0, { timeout: 30_000 })
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

async function fetchDemoZevId(request: APIRequestContext, headers: Record<string, string>): Promise<string | null> {
  const zevsResp = await request.get(`${API_BASE}/zev/zevs/`, { headers })
  expect(zevsResp.ok(), `Fetching ZEVs failed (${zevsResp.status()})`).toBeTruthy()
  const zevsBody = await zevsResp.json() as { results?: Array<{ id: string; name: string }> }
  return zevsBody.results?.find(z => z.name === DEMO_ZEV_NAME)?.id ?? null
}

/** Resolve the id of the data-bearing demo ZEV via the admin API. */
export async function resolveDemoZevId(page: Page): Promise<string | null> {
  return fetchDemoZevId(page.request, { Authorization: `Bearer ${await getAdminToken(page)}` })
}

/** The demo participant's account and live participation in the demo ZEV. */
async function findDemoParticipant(request: APIRequestContext, headers: Record<string, string>) {
  const zevId = await fetchDemoZevId(request, headers)
  expect(zevId, MISSING_DEMO_ZEV).toBeTruthy()

  // The list is paginated and has no email filter; walk it.
  let account: User | undefined
  for (let url: string | null = `${API_BASE}/auth/users/`; url && !account;) {
    const usersResp = await request.get(url, { headers })
    expect(usersResp.ok(), `Fetching users failed (${usersResp.status()})`).toBeTruthy()
    const usersBody = await usersResp.json() as { results: User[]; next: string | null }
    account = usersBody.results.find(user => user.email === DEMO_PARTICIPANT_EMAIL)
    url = usersBody.next
  }
  expect(account, `${DEMO_PARTICIPANT_EMAIL} not found — run seed_demo`).toBeTruthy()
  const live = account!.memberships?.find(entry => entry.zev === zevId)?.participants.find(row => row.live)
  expect(live, `${DEMO_PARTICIPANT_EMAIL} has no live participation in ${DEMO_ZEV_NAME}`).toBeTruthy()
  return { zevId: zevId!, account: account!, participantId: live!.id }
}

/** The demo participant's newest invoice, which 08b opens. */
export async function findDemoInvoice(
  request: APIRequestContext, headers: Record<string, string>,
): Promise<{ id: string; pdf_url: string | null }> {
  const { zevId, participantId } = await findDemoParticipant(request, headers)
  const resp = await request.get(
    `${API_BASE}/invoices/invoices/?zev_id=${zevId}&participant_id=${participantId}`, { headers })
  expect(resp.ok(), `Invoice list request failed (${resp.status()})`).toBeTruthy()
  const body = await resp.json() as { results: Array<{ id: string; pdf_url: string | null }> }
  expect(body.results.length, `${DEMO_PARTICIPANT_EMAIL} has no invoice — run seed_demo`).toBeGreaterThan(0)
  return body.results[0]
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
 * Impersonate the demo participant. Fails unless the seed has her as a plain
 * user with a live participation in the demo ZEV and, when asked, a sent or
 * paid invoice.
 */
export async function impersonateDemoParticipant(page: Page, { requireSentInvoice = false } = {}) {
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  const { zevId, account, participantId } = await findDemoParticipant(page.request, headers)

  // Any of these would render the manager shell instead.
  const memberships = account.memberships ?? []
  expect(account.role, `${DEMO_PARTICIPANT_EMAIL} must be a plain user`).toBe('user')
  expect(memberships.every(entry => entry.access === null),
    `${DEMO_PARTICIPANT_EMAIL} must hold no access grant`).toBe(true)
  expect(memberships.every(entry => !entry.roles?.length),
    `${DEMO_PARTICIPANT_EMAIL} must hold no issuer or representative role`).toBe(true)

  if (requireSentInvoice) {
    // Personal invoice captures need a billed participant: drafts are hidden
    // from the participant's list.
    const response = await page.request.get(
      `${API_BASE}/invoices/invoices/?zev_id=${zevId}&participant_id=${participantId}&status=sent,paid`, { headers })
    expect(response.ok(), `Fetching sent invoices failed (${response.status()})`).toBeTruthy()
    const body = await response.json() as { results: unknown[] }
    expect(body.results.length, `${DEMO_PARTICIPANT_EMAIL} has no sent or paid invoice`).toBeGreaterThan(0)
  }

  // Call the impersonate endpoint — the server rotates the cookies automatically.
  const impResp = await page.request.post(`${API_BASE}/auth/users/${account.id}/impersonate/`, { headers })
  expect(impResp.ok(), `Impersonation failed (${impResp.status()})`).toBeTruthy()

  // The app detects impersonation from the JWT claim (impersonated_by) returned by
  // /auth/me/, so no localStorage injection is needed.
  await page.addInitScript(() => {
    // PDF frames also run init scripts but can have no localStorage.
    if (window.top !== window) return
    try {
      localStorage.setItem('openzev.sidebarCollapsed', 'false')
    } catch {
      // Storage may be unavailable.
    }
  })
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
  // Uncap viewport-relative tables, and the tariff detail pane (which scrolls
  // on its own, capped at the viewport), while measuring and capturing: both
  // caps are 100dvh-relative and would feed a ~1:1 slope into the solver.
  // Where a cap would not bind, pixels match shipped CSS.
  const styleHandle = await page.addStyleTag({
    content: '.table-scroll, .tariff-split[data-layout] .tariff-pane { max-height: none !important; }',
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
    await styleHandle.evaluate((el) => el.parentNode?.removeChild(el)).catch(() => {})
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
 * Rewrite a capture in place as a 256-colour palette PNG.
 *
 * UI screenshots use few colours, so this cuts the user-guide set to about a
 * third of its size with no visible change, and every regenerated set adds
 * correspondingly less to Git history (#723). Output is deterministic, so an
 * unchanged screen still produces an unchanged file.
 */
export async function quantizePng(file: string) {
  const png = await sharp(file).png({ palette: true, effort: 10, compressionLevel: 9 }).toBuffer()
  await writeFile(file, png)
}

export const PDF_VIEWER_URL = 'chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/'

/** Wait for the native PDF plugin to finish loading a nonempty document. */
export async function assertPdfLoaded(page: Page, timeout = 15_000) {
  await expect
    .poll(
      async () => {
        const viewer = page.frames().find(f => f.url().startsWith(PDF_VIEWER_URL))
        if (!viewer) return { loaded: false, state: 'no viewer' }
        try {
          return await viewer.evaluate(() => {
            const toolbar = document.querySelector('pdf-viewer')?.shadowRoot
              ?.querySelector('viewer-toolbar') as (HTMLElement & {
                loadProgress: number
                docLength: number
              }) | null
            return {
              loaded: toolbar?.loadProgress === 100 && toolbar.docLength > 0,
              loadProgress: toolbar?.loadProgress,
              docLength: toolbar?.docLength,
            }
          })
        } catch (error) {
          if (error instanceof Error && /Execution context was destroyed|Frame was detached/.test(error.message)) {
            return { loaded: false, state: 'frame not ready' }
          }
          throw error
        }
      },
      {
        message: 'PDF viewer did not load a nonempty document — use SCREENSHOT_CHANNEL=chromium and check the PDF response',
        timeout,
      }
    )
    .toEqual(expect.objectContaining({ loaded: true }))
}

/**
 * Close the viewer's thumbnail sidebar: Chromium opens it by default and
 * `#navpanes=0` doesn't reach the viewer on blob URLs, so click the toolbar
 * toggle (`#sidenavToggle`, via `aria-expanded`) instead.
 */
export async function closePdfSidebar(page: Page, timeout = 5_000) {
  const viewer = page.frames().find(f => f.url().startsWith(PDF_VIEWER_URL))
  if (!viewer) throw new Error('PDF viewer missing — call assertPdfLoaded before closing its sidebar')
  const toggle = viewer.locator('#sidenavToggle')
  await expect(toggle, 'PDF viewer sidebar toggle missing or invalid — Chromium viewer DOM changed?')
    .toHaveAttribute('aria-expanded', /^(true|false)$/, { timeout })
  if (await toggle.getAttribute('aria-expanded') === 'false') return
  // Chromium hides the sidebar control in narrow embeds; click it directly.
  await toggle.evaluate(button => (button as HTMLElement).click())
  await expect(toggle, 'PDF viewer sidebar did not close — Chromium viewer DOM changed?')
    .toHaveAttribute('aria-expanded', 'false', { timeout })
}
