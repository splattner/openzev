import { test, expect } from '@playwright/test'
import { collectBrowserErrors, navigateTo, pinDemoZev } from './helpers'

for (const [name, path] of [
  ['communities', '/admin/zevs'],
  ['accounts', '/admin/accounts'],
  ['VAT rates', '/admin/system-settings?tab=vat'],
  ['features', '/admin/system-settings?tab=features'],
]) {
  test(`${name} tables contain overflow and align their header band`, async ({ page }, testInfo) => {
    const errors = collectBrowserErrors(page)
    await navigateTo(page, path)
    const table = page.locator('main table').first()
    await expect(table.locator('tbody tr').first()).toBeVisible()
    // Extend only this browser's DOM so short lists exercise vertical scrolling too.
    await table.locator('tbody').evaluate(body => {
      const row = body.querySelector('tr')!
      while (body.children.length < 30) body.append(row.cloneNode(true))
    })
    const scroll = page.locator('main .table-scroll').first()
    for (const width of [1440, 1080, 940, 400]) {
      await page.setViewportSize({ width, height: 850 })
      await scroll.evaluate(element => { element.scrollTop = 0; element.scrollLeft = 0 })
      await table.scrollIntoViewIfNeeded()
      await page.screenshot({ path: testInfo.outputPath(`table-${width}.png`) })
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `page overflow at ${width}px`).toBe(true)
      if (name !== 'features') {
        expect(await table.evaluate(element => {
          const card = element.closest('.table-card')!
          return element.querySelector('th')!.getBoundingClientRect().top - card.getBoundingClientRect().top - card.clientTop
        }), `white strip at ${width}px`).toBeCloseTo(0, 0)
      }
      await scroll.evaluate(element => { element.scrollTop = 150; element.scrollLeft = element.scrollWidth })
      expect(await scroll.evaluate(element => element.scrollTop)).toBeGreaterThan(0)
      await expect.poll(() => table.locator('th').first().evaluate(element =>
        element.getBoundingClientRect().top - element.closest('.table-scroll')!.getBoundingClientRect().top,
      )).toBeCloseTo(0, 0)

      // The header follows its panel during page scrolling, rather than sticking to the viewport.
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }))
      const before = (await table.locator('th').first().boundingBox())!.y
      await page.evaluate(() => window.scrollBy({ top: 80, behavior: 'instant' }))
      const pageScroll = await page.evaluate(() => scrollY)
      expect(pageScroll).toBeGreaterThan(0)
      expect((await table.locator('th').first().boundingBox())!.y).toBeCloseTo(before - pageScroll, 0)

      const lastControl = table.locator('tbody button, tbody input').last()
      if (await lastControl.count()) {
        await lastControl.scrollIntoViewIfNeeded()
        expect(await page.evaluate(() => scrollX), 'table controls must not scroll the page sideways').toBe(0)
      }
    }
    expect(errors).toEqual([])
  })
}

test('tariff cards retain only their category heading', async ({ page }) => {
  await pinDemoZev(page)
  await navigateTo(page, '/tariffs')
  await page.setViewportSize({ width: 940, height: 850 })
  const tables = page.locator('.tariff-table')
  expect(await tables.count()).toBeGreaterThan(1)
  for (const table of await tables.all()) {
    const labels = await table.locator('thead th').evaluateAll(cells => cells.filter(cell => {
      const style = getComputedStyle(cell)
      return style.display !== 'none' && style.clipPath === 'none' && cell.getBoundingClientRect().width > 1
    }).map(cell => cell.textContent!.trim()))
    expect(labels).toHaveLength(1)
    expect(labels[0]).toBe((await table.locator('thead th').first().textContent())!.trim())
  }
})

for (const [kind, name] of [
  ['words', 'Genossenschaft Sonnenhof Wohnbau und Gewerbe Oberwinterthur'],
  ['unbroken token', 'UnbrokenOrganisationIdentifier'.repeat(8)],
]) {
  test(`document recipient ${kind} wrap without overflowing`, async ({ page }) => {
    await page.route('**/api/v1/inbox/documents/**', async route => {
      const response = await route.fetch()
      const data = await response.json()
      const records = Array.isArray(data) ? data : data.results
      records[0] = { ...records[0], participant_name: name, batch_id: null }
      await route.fulfill({ response, json: data })
    })
    await pinDemoZev(page)
    await navigateTo(page, '/documents')
    await page.setViewportSize({ width: 940, height: 850 })
    const table = page.locator('.doc-wide table')
    const recipient = table.locator('tbody tr').filter({ hasText: name }).first().locator('td').nth(1)
    await expect(recipient).toHaveText(name)
    expect(await table.evaluate(element => element.getBoundingClientRect().width <= element.parentElement!.clientWidth + 1)).toBe(true)
    expect(await recipient.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
    expect(await recipient.evaluate(element => {
      const range = document.createRange()
      range.selectNodeContents(element)
      return new Set(Array.from(range.getClientRects(), rect => rect.top)).size > 1
    })).toBe(true)
  })
}
