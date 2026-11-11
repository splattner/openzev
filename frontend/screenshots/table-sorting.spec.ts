import { expect, test, type Page } from '@playwright/test'
import { goToPreviousPeriod, navigateTo, pinDemoZev } from './helpers'

function collectErrors(page: Page) {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => {
    // Optional source discovery answers 404 while its feature flag is off.
    const disabledDiscovery = message.location().url.includes('/metering/supplementary/sources/eligible/') && message.text().includes('404')
    if (message.type() === 'error' && !disabledDiscovery) errors.push(message.text())
  })
  return errors
}

for (const width of [1440, 400]) {
  test.describe(`record table sorting at ${width}px`, () => {
    test.use({ viewport: { width, height: 1000 } })

    test('metering-point headings update the URL and sort the first building', async ({ page }, testInfo) => {
      const errors = collectErrors(page)
      await pinDemoZev(page)
      await navigateTo(page, '/metering/points')
      const table = page.locator('.metering-point-list').first()
      await expect(table.locator('tbody.metering-point-card').nth(1)).toBeAttached()
      const ids = () => table.locator('.metering-point-id-main strong').allTextContents()
      const original = await ids()
      expect(new Set(original).size).toBeGreaterThan(1)
      const collator = new Intl.Collator('de-CH', { numeric: true })
      const header = table.locator('th').first()
      await expect(header.locator('button')).toBeVisible()
      await expect(table.locator('th[aria-sort]')).toHaveCount(0)
      await expect(header.locator('span[aria-hidden]')).toHaveText('')
      expect(original).toEqual([...original].sort(collator.compare))
      await header.locator('button').click()
      await expect(page).toHaveURL(/sort=meter_id/)
      await expect(header).toHaveAttribute('aria-sort', 'ascending')
      await page.reload()
      await expect(header).toHaveAttribute('aria-sort', 'ascending')
      await header.locator('button').click()
      await expect(page).toHaveURL(/sort=-meter_id/)
      await expect.poll(ids).toEqual([...original].sort((a, b) => collator.compare(b, a)))
      await expect(header).toHaveAttribute('aria-sort', 'descending')
      await header.locator('button').click()
      await expect.poll(ids).toEqual([...original].sort(collator.compare))
      await expect(header).toHaveAttribute('aria-sort', 'ascending')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      expect(errors).toEqual([])
      await page.screenshot({ path: testInfo.outputPath('metering-points.png'), fullPage: true })
    })

    for (const [name, route, selector] of [
      ['dashboard', '/dashboard', '.participant-table'],
      ['invoices', '/billing/invoices', '.invoice-rows table'],
      ['documents', '/documents', '.doc-wide table'],
      ['tariffs', '/tariffs', '.tariff-table'],
    ]) {
      test(`${name} exposes working sort controls`, async ({ page }, testInfo) => {
        const errors = collectErrors(page)
        await pinDemoZev(page)
        await navigateTo(page, route)
        if (name === 'dashboard') await goToPreviousPeriod(page)
        const table = page.locator(selector).first()
        await expect(table.locator('tbody tr').first()).toBeAttached()
        const values = () => table.locator('tbody tr').evaluateAll((rows, kind) => rows.map(row => {
          if (kind === 'dashboard') return row.querySelector('.participant-select')!.textContent!.trim()
          if (kind === 'tariffs') return row.querySelector('.tariff-select')!.textContent!.trim()
          if (kind === 'invoices') return row.querySelector('.invoice-row-name strong')!.textContent!.trim()
          return Array.from(row.children[0].childNodes).filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => node.textContent).join('').trim()
        }), name)
        const original = await values()
        expect(new Set(original).size).toBeGreaterThan(1)
        const collator = new Intl.Collator('de-CH', { numeric: true })
        const header = table.locator('th').first()
        await expect(header.locator('button')).toBeVisible()
        if (name === 'tariffs') {
          await expect(table.locator('th.numeric button')).toBeVisible()
          for (const category of await page.locator('.tariff-table').all()) {
            if (await category.locator('tbody tr').count() === 1) {
              await expect(category.locator('th button, th[aria-sort]')).toHaveCount(0)
            }
          }
        }
        await header.locator('button').click()
        await expect(header).toHaveAttribute('aria-sort', 'ascending')
        expect(await values()).toEqual([...original].sort(collator.compare))
        await header.locator('button').click()
        await expect(header).toHaveAttribute('aria-sort', 'descending')
        expect(await values()).toEqual([...original].sort((left, right) => collator.compare(right, left)))
        if (name === 'tariffs') {
          const prices = () => table.locator('tbody td.numeric').evaluateAll(cells => cells.map(cell => {
            const lines = [...cell.querySelectorAll('div')]
            return Math.min(...lines.map(line => Number(line.textContent!.replace(/^≈\s*/, ''))))
          }))
          const originalPrices = await prices()
          expect(originalPrices.every(Number.isFinite)).toBe(true)
          expect(new Set(originalPrices).size).toBeGreaterThan(1)
          const price = table.locator('th.numeric')
          await price.locator('button').click()
          await expect(price).toHaveAttribute('aria-sort', 'descending')
          expect(await prices()).toEqual([...originalPrices].sort((a, b) => b - a))
          await price.locator('button').click()
          await expect(price).toHaveAttribute('aria-sort', 'ascending')
          expect(await prices()).toEqual([...originalPrices].sort((a, b) => a - b))
        }
        await expect(table.locator('th[aria-sort]')).toHaveCount(1)
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
        expect(errors).toEqual([])
        await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true })
      })
    }
  })
}
