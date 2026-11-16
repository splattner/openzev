import { test, expect, type Page } from '@playwright/test'
import { API_BASE, collectBrowserErrors, getAdminToken, impersonateDemoParticipant, navigateTo, pinDemoZev } from './helpers'

for (const [name, path, selector] of [
  ['participants', '/participants', '.participant-rows'],
  ['billing', '/billing/invoices', '.invoice-rows'],
  ['documents', '/documents', '.table-card:has(.doc-wide)'],
  ['admin invoices', '/admin/invoices', '.card:has(.data-table)'],
]) {
  test(`${name} table meets its sheet edges across breakpoints`, async ({ page }, testInfo) => {
    const errors = collectBrowserErrors(page)
    await pinDemoZev(page)
    await navigateTo(page, path)
    const sheet = page.locator(selector).first()
    await expect(sheet.locator('tbody tr').first()).toBeAttached()
    for (const width of [1440, 1180, 1080, 940, 400]) {
      await page.setViewportSize({ width, height: 900 })
      if (width <= 400) {
        await expect.poll(() => page.locator('#app-sidebar').evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0)
      }
      if (name !== 'admin invoices') {
        await expect.poll(() => sheet.evaluate(element => {
          const head = element.querySelector('thead')!
          if (getComputedStyle(head).clipPath === 'inset(50%)') return !head.querySelector('button')
          const gap = head.getBoundingClientRect().top - element.getBoundingClientRect().top - element.clientTop
          const boxes = Array.from(head.querySelectorAll('th.sortable-header'), cell => cell.getBoundingClientRect())
            .filter(box => box.width && box.height)
          const singleLine = !head.classList.contains('responsive-table-head') || boxes.every(box => Math.abs(box.top - boxes[0].top) < 1)
          const noOverlap = boxes.every((a, index) => boxes.slice(index + 1).every(b =>
            Math.min(a.right, b.right) - Math.max(a.left, b.left) <= 0.5 ||
            Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) <= 0.5))
          return Math.abs(gap) < 0.5 && singleLine && noOverlap
        }), { message: `header wraps, overlaps or leaves a gap at ${width}px` }).toBe(true)
      }
      if (name === 'admin invoices' || (name === 'documents' && width > 640)) {
        expect(await sheet.evaluate(element => {
          const table = element.querySelector('.data-table, .table-scroll')!
          return element.getBoundingClientRect().bottom - table.getBoundingClientRect().bottom - element.clientTop
        }), `bottom gap at ${width}px`).toBeCloseTo(0, 0)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`table-${width}.png`), fullPage: true })
    }
    expect(errors).toEqual([])
  })
}

for (const language of ['en', 'de', 'fr', 'it']) {
  test(`participant cards retain sorting and focus across the container boundary in ${language}`, async ({ page }, testInfo) => {
    await page.addInitScript(lang => localStorage.setItem('openzev.language', lang), language)
    await pinDemoZev(page)
    await page.setViewportSize({ width: 1600, height: 900 })
    await navigateTo(page, '/participants')
    const sheet = page.locator('.participant-rows')
    const table = sheet.getByRole('table')
    const head = table.locator('thead')
    const header = head.locator('th').first()
    const names = () => sheet.locator('.invoice-row-name strong').allTextContents()
    const original = await names()
    const collator = new Intl.Collator(language, { numeric: true })
    const ascending = [...original].sort(collator.compare)
    const descending = [...original].sort((a, b) => collator.compare(b, a))
    const boundary = 56 * await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize))
    const resize = async (width: number) => {
      await sheet.evaluate((element, size) => {
        element.style.boxSizing = 'content-box'
        element.style.width = `${size}px`
      }, width)
      await expect(head).toHaveAttribute('data-card-layout', width <= boundary ? 'true' : 'false')
      await expect(table.getByRole('columnheader')).toHaveCount(6)
    }

    await resize(boundary + 1)
    await header.locator('button').click()
    await header.locator('button').click()
    await expect(header).toHaveAttribute('aria-sort', 'descending')
    await expect.poll(names).toEqual(descending)
    await header.locator('button').focus()
    for (const width of [boundary, boundary - 1]) {
      await resize(width)
      await expect(head).toHaveCSS('clip-path', 'inset(50%)')
      await expect(head.locator('button')).toHaveCount(0)
      await expect(table).toBeFocused()
      await expect.poll(names).toEqual(descending)
    }
    await page.screenshot({ path: testInfo.outputPath(`participants-${language}-cards.png`), fullPage: true })

    await resize(boundary + 1)
    await expect(header).toHaveAttribute('aria-sort', 'descending')
    await expect.poll(names).toEqual(descending)
    await header.locator('button').click()
    await expect.poll(names).toEqual(original)
    await header.locator('button').click()
    await expect.poll(names).toEqual(ascending)
    await page.screenshot({ path: testInfo.outputPath(`participants-${language}-table.png`), fullPage: true })

    const search = page.locator('main input').first()
    await search.focus()
    await resize(boundary)
    await expect(search).toBeFocused()
    await expect.poll(names).toEqual(ascending)
    await resize(boundary + 1)
    await expect(search).toBeFocused()
    await expect(header).toHaveAttribute('aria-sort', 'ascending')
  })
}

const PROBE_PREFIX = 'Layout Probe '
const PROBE_COUNT = 10

async function prepareProbeZevs(page: Page) {
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  const meResp = await page.request.get(`${API_BASE}/auth/me/`, { headers })
  expect(meResp.ok(), `Fetching /auth/me/ failed (${meResp.status()})`).toBeTruthy()
  const user = await meResp.json()
  const results = Array.from({ length: PROBE_COUNT }, (_, index) => ({
    id: `layout-probe-${index + 1}`,
    name: `${PROBE_PREFIX}${String(index + 1).padStart(2, '0')}`,
    owner: user.id,
  }))
  await page.route(/\/api\/v1\/zev\/zevs\/(?:\?.*)?$/, (route) => route.fulfill({
    json: { count: results.length, next: null, previous: null, results },
  }))
  // Selection stays local to this browser, including the saved preference.
  await page.route(/\/api\/v1\/auth\/me\/$/, (route) => {
    if (route.request().method() !== 'PATCH') return route.continue()
    return route.fulfill({ json: { ...user, ...route.request().postDataJSON() } })
  })
}

test('a long community list scrolls inside its menu and stays on screen', async ({ page }) => {
  await prepareProbeZevs(page)
  await navigateTo(page, '/tariffs')
  const switcher = page.locator('main .community-switch')
  for (const size of [
    { width: 1440, height: 600 },
    { width: 1280, height: 400 },
    { width: 740, height: 390 },
    { width: 390, height: 600 },
  ]) {
    await page.setViewportSize(size)
    await switcher.click()
    const menu = page.locator('.community-menu')
    await expect(menu).toBeVisible()
    const box = await menu.boundingBox()
    expect(box, 'community menu has no box').not.toBeNull()
    expect(box!.y, 'menu starts above the viewport').toBeGreaterThanOrEqual(0)
    expect(box!.y + box!.height, 'menu ends below the viewport').toBeLessThanOrEqual(size.height)
    expect(box!.x + box!.width, 'menu ends right of the viewport').toBeLessThanOrEqual(size.width)
    expect(box!.height, 'community menu was crushed').toBeGreaterThanOrEqual(100)
    if (size.height <= 400) {
      expect(await menu.evaluate((el) => el.scrollHeight > el.clientHeight), 'the list scrolls inside the menu').toBe(true)
    }
    const target = page.getByRole('menuitem', { name: `${PROBE_PREFIX}10` })
    await target.scrollIntoViewIfNeeded()
    await target.click()
    await expect(menu).toBeHidden()
    await expect(switcher).toContainText(`${PROBE_PREFIX}10`)
  }
})

// The account panel is the only way to log out or change the language, and it
// opens upwards inside the sidebar, which scrolls and clips its overflow.
test('the account panel opens on screen, inside the sidebar, at short viewports', async ({ page }) => {
  await navigateTo(page, '/tariffs')
  for (const size of [
    { width: 1280, height: 400 },
    { width: 740, height: 390 },
    { width: 390, height: 600 },
  ]) {
    await page.setViewportSize(size)
    const hamburger = page.locator('.mobile-menu-button')
    if (await hamburger.isVisible()) {
      await hamburger.click()
      await expect(page.locator('.sidebar.mobile-open')).toBeVisible()
    }
    const trigger = page.locator('.sidebar-footer .user-menu-trigger')
    await trigger.click()
    const panel = page.locator('#user-menu-list')
    await expect(panel).toBeVisible()
    const sidebar = await page.locator('#app-sidebar').boundingBox()
    const box = await panel.boundingBox()
    expect(box, 'account panel has no box').not.toBeNull()
    expect(box!.y, 'panel starts above the viewport').toBeGreaterThanOrEqual(0)
    expect(box!.y + box!.height, 'panel ends below the viewport').toBeLessThanOrEqual(size.height)
    expect(box!.y, 'panel starts above the sidebar, which clips it').toBeGreaterThanOrEqual(sidebar!.y)
    expect(box!.x + box!.width, 'panel ends right of the sidebar, which clips it').toBeLessThanOrEqual(sidebar!.x + sidebar!.width)
    // Every entry, down to the last (log out), is on screen and reachable.
    await expect(panel.locator('.user-menu-item').last()).toBeInViewport()
    await trigger.click()
    await expect(panel).toBeHidden()
    if (await hamburger.isVisible()) {
      await page.keyboard.press('Escape')
      await expect(page.locator('.sidebar.mobile-open')).toHaveCount(0)
    }
  }
})

async function prepareFocusPage(page: Page, width = 1366) {
  await page.setViewportSize({ width, height: 800 })
  await page.addInitScript(() => {
    localStorage.setItem('openzev.sidebarCollapsed', 'true')
    localStorage.setItem('openzev.language', 'en')
  })
  await navigateTo(page, '/account')
}

for (const impersonating of [false, true]) {
  test(`phone keyboard focus clears sticky headers when impersonating=${impersonating}`, async ({ page }) => {
    await impersonateDemoParticipant(page, { requireSentInvoice: true })
    if (!impersonating) {
      // Keep the same participant content while exercising the ordinary shell.
      await page.route('**/auth/me/', async route => {
        const response = await route.fetch()
        await route.fulfill({ response, json: { ...await response.json(), impersonated_by: null } })
      })
    }
    await page.setViewportSize({ width: 400, height: 600 })
    await navigateTo(page, '/me/documents')
    await expect(page.locator('.impersonation-banner')).toHaveCount(impersonating ? 1 : 0)
    const first = page.locator('.doc-cards button').first()
    await page.locator('.doc-cards button').nth(1).focus()
    await first.evaluate(el => window.scrollBy(0, el.getBoundingClientRect().top - 8))
    await page.keyboard.press('Shift+Tab')
    await expect(first).toBeFocused()
    const header = (await page.locator('.top-nav').boundingBox())!
    expect((await first.boundingBox())!.y).toBeGreaterThanOrEqual(header.y + header.height)
  })
}

test('the identity strip spans the shell and is covered by the open phone drawer scrim', async ({ page }) => {
  await impersonateDemoParticipant(page)
  await prepareFocusPage(page)
  const banner = page.locator('.shell > .impersonation-banner')
  for (const collapsed of [true, false]) {
    if (!collapsed) await page.locator('.sidebar-collapse-button').click()
    const box = (await banner.boundingBox())!
    expect(box.x).toBe(0)
    expect(box.width).toBe(await page.evaluate(() => document.documentElement.clientWidth))
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    expect((await banner.boundingBox())!.y).toBe(0)
    await page.evaluate(() => window.scrollTo(0, 0))
  }
  await page.setViewportSize({ width: 400, height: 600 })
  await page.locator('.mobile-menu-button').click()
  await expect(banner).toHaveAttribute('inert', '')
  const stop = banner.locator('button')
  await stop.evaluate(el => el.focus())
  await expect(stop).not.toBeFocused()
  const box = (await stop.boundingBox())!
  const point = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
  expect(await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.classList.contains('sidebar-overlay'), point)).toBe(true)
  await page.mouse.click(point.x, point.y)
  await expect(banner).not.toHaveAttribute('inert')
  await stop.focus()
  await expect(stop).toBeFocused()
})

test('breakpoint changes preserve body focus outside navigation', async ({ page }) => {
  await prepareFocusPage(page, 400)
  expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true)
  await page.setViewportSize({ width: 1366, height: 768 })
  await expect(page.locator('.shell-collapsed')).toBeVisible()
  expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true)
})

test('breakpoint changes recover focus from hidden navigation controls', async ({ page }) => {
  await prepareFocusPage(page)
  const collapse = page.locator('.sidebar-collapse-button')
  const hamburger = page.locator('.mobile-menu-button')
  await collapse.focus()
  await page.setViewportSize({ width: 400, height: 800 })
  await expect(collapse).toBeHidden()
  await expect(hamburger).toBeFocused()
  await hamburger.press('Enter')
  await expect(page.locator('.sidebar.mobile-open')).toBeVisible()
  await expect(page.locator('#app-sidebar')).toBeInViewport({ ratio: 0.95 })
  await expect(page.locator('.mobile-sidebar-close')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(hamburger).toBeFocused()
  await expect(page.locator('#app-sidebar')).not.toBeInViewport()
  await page.setViewportSize({ width: 1366, height: 768 })
  await expect(collapse).toBeFocused()
  await expect(collapse).toBeVisible()
  await expect(page.locator('.sidebar.mobile-open')).toHaveCount(0)
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden')
  await expect(page.locator('nav a[href="/admin/system-settings"]')).toHaveAccessibleName('Platform: Settings')
  expect(await page.evaluate(() => localStorage.getItem('openzev.sidebarCollapsed'))).toBe('true')
})

test('the phone drawer is modal for the keyboard', async ({ page }) => {
  await prepareFocusPage(page, 400)
  const sidebar = page.locator('#app-sidebar')
  const hamburger = page.locator('.mobile-menu-button')
  const focusedIn = () => page.evaluate(() => {
    const active = document.activeElement
    if (active === document.body) return 'body'
    if (active?.closest('#app-sidebar')) return 'sidebar'
    // The skip link sits before the drawer and closes it.
    return active?.classList.contains('skip-link') ? 'skip-link' : 'page'
  })

  // Closed, the off-canvas links are not tabbable: focus never disappears off screen.
  await expect(sidebar).toHaveAttribute('inert', '')
  for (let step = 0; step < 40; step++) {
    await page.keyboard.press('Tab')
    expect(await focusedIn(), `tab ${step + 1} entered the closed drawer`).not.toBe('sidebar')
  }

  // Open, focus moves in and cannot reach the page behind the scrim.
  await hamburger.focus()
  await hamburger.press('Enter')
  await expect(page.locator('.mobile-sidebar-close')).toBeFocused()
  await expect(sidebar).toHaveAttribute('role', 'dialog')
  for (let step = 0; step < 40; step++) {
    await page.keyboard.press('Tab')
    expect(await focusedIn(), `tab ${step + 1} reached the page behind the drawer`).not.toBe('page')
  }

  await page.keyboard.press('Escape')
  await expect(hamburger).toBeFocused()
  await expect(sidebar).toHaveAttribute('inert', '')

  // The close button and the skip link end it as well.
  await hamburger.press('Enter')
  await page.locator('.mobile-sidebar-close').press('Enter')
  await expect(hamburger).toBeFocused()
  await hamburger.press('Enter')
  await page.locator('.skip-link').focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('.sidebar.mobile-open')).toHaveCount(0)
  await expect(page.locator('#main-content')).toBeFocused()
})

test('breakpoint changes preserve a textbox value, focus and selection', async ({ page }) => {
  await prepareFocusPage(page)
  const input = page.locator('input[name="first_name"]')
  await input.fill('Unsaved profile name')
  await input.evaluate((node: HTMLInputElement) => node.setSelectionRange(2, 8))
  for (const width of [400, 1366]) {
    await page.setViewportSize({ width, height: 800 })
    if (width === 400) await expect(page.locator('.sidebar-collapse-button')).toBeHidden()
    else await expect(page.locator('.sidebar-collapse-button')).toBeVisible()
    await expect(input).toBeFocused()
    await expect(input).toHaveValue('Unsaved profile name')
    expect(await input.evaluate((node: HTMLInputElement) => [node.selectionStart, node.selectionEnd])).toEqual([2, 8])
  }
})
