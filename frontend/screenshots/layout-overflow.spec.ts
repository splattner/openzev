import { test, expect, type Page } from '@playwright/test'
import { API_BASE, getAdminToken, navigateTo } from './helpers'

const PROBE_PREFIX = 'Layout Probe '
const PROBE_COUNT = 10

async function createProbeZevs(page: Page, ids: string[]) {
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  const meResp = await page.request.get(`${API_BASE}/auth/me/`, { headers })
  expect(meResp.ok(), `Fetching /auth/me/ failed (${meResp.status()})`).toBeTruthy()
  const owner = (await meResp.json() as { id: number }).id
  for (let i = 1; i <= PROBE_COUNT; i++) {
    const resp = await page.request.post(`${API_BASE}/zev/zevs/`, {
      headers,
      data: { name: `${PROBE_PREFIX}${String(i).padStart(2, '0')}`, owner },
    })
    expect(resp.ok(), `Probe ZEV create failed (${resp.status()})`).toBeTruthy()
    ids.push((await resp.json() as { id: string }).id)
  }
}

async function deleteProbeZevs(page: Page, ids: string[]) {
  const headers = { Authorization: `Bearer ${await getAdminToken(page)}` }
  for (const id of ids) {
    const resp = await page.request.delete(`${API_BASE}/zev/zevs/${id}/`, { headers })
    if (!resp.ok()) console.log(`  probe ZEV cleanup failed for ${id} (${resp.status()})`)
  }
}

async function openSwitcher(page: Page) {
  await page.locator('.sidebar-zev-menu .user-menu-trigger').click()
  await expect(page.locator('#zev-menu-list')).toBeVisible()
}

async function expectNavSurvives(page: Page) {
  const viewport = page.viewportSize()
  expect(viewport, 'no viewport size').not.toBeNull()
  const topBox = await page.locator('.sidebar-top').boundingBox()
  expect(topBox, 'sidebar nav has no box — it collapsed').not.toBeNull()
  expect(topBox!.height).toBeGreaterThanOrEqual(70)
  await expect(page.locator('.sidebar-top nav a').first()).toBeVisible()
  await page.locator('.sidebar').evaluate((el) => { el.scrollTop = el.scrollHeight })
  const footerBox = await page.locator('.sidebar-footer').boundingBox()
  expect(footerBox, 'sidebar footer has no box').not.toBeNull()
  expect(footerBox!.y, 'footer starts above the viewport').toBeGreaterThanOrEqual(0)
  expect(footerBox!.y + footerBox!.height, 'footer ends below the viewport').toBeLessThanOrEqual(viewport!.height)
}

async function expectListUsable(page: Page) {
  const listBox = await page.locator('#zev-menu-list .zev-dropdown-list').boundingBox()
  expect(listBox, 'community list has no box — it was crushed').not.toBeNull()
  expect(listBox!.height).toBeGreaterThanOrEqual(100)
}

async function selectLastProbe(page: Page) {
  const target = page.locator('.zev-dropdown-item', { hasText: `${PROBE_PREFIX}10` })
  await target.scrollIntoViewIfNeeded()
  await target.click()
  await expect(page.locator('#zev-menu-list')).toBeHidden()
  await expect(page.locator('.sidebar-zev-menu .user-menu-trigger')).toContainText(`${PROBE_PREFIX}10`)
}

test('open community list never evicts the sidebar navigation', async ({ page }) => {
  const probeIds: string[] = []
  try {
    await createProbeZevs(page, probeIds)

    let first = true
    for (const size of [
      { width: 1440, height: 600, drawer: false },
      { width: 1280, height: 400, drawer: false },
      { width: 740, height: 390, drawer: true },
      { width: 390, height: 600, drawer: true },
    ]) {
      await page.setViewportSize(size)
      await navigateTo(page, '/')
      if (size.drawer) {
        await page.locator('.mobile-menu-button').click()
        await expect(page.locator('.sidebar.mobile-open')).toBeVisible()
      }
      await openSwitcher(page)
      if (first) {
        const scrollable = await page.evaluate(() => {
          const list = document.querySelector('#zev-menu-list .zev-dropdown-list')
          return list ? list.scrollHeight > list.clientHeight : null
        })
        expect(scrollable, 'community list should scroll internally').toBe(true)
        first = false
      }
      await expectListUsable(page)
      await expectNavSurvives(page)
      await selectLastProbe(page)
    }
  } finally {
    await deleteProbeZevs(page, probeIds)
  }
})
