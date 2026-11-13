import { expect, test } from '@playwright/test'
import { navigateTo, pinDemoZev } from './helpers'

for (const width of [1440, 400]) {
  for (const [name, path] of [['accounts', '/admin/accounts/users'], ['communities', '/admin/zevs']]) {
    test(`${name} row actions stay neutral and on one line at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 })
      await page.addInitScript(() => localStorage.setItem('openzev.language', 'en'))
      expect(await pinDemoZev(page)).toBe(true)
      await navigateTo(page, path)
      const groups = page.locator('tbody .actions-cell-content')
      await expect(groups.first()).toBeVisible()
      for (const group of await groups.all()) {
        const buttons = group.getByRole('button')
        await expect(buttons.first()).toHaveAccessibleName(/^Edit: /)
        await expect(buttons.first()).toHaveClass(/button-secondary/)
        const tops = await buttons.evaluateAll(elements => elements.map(element => Math.round(element.getBoundingClientRect().top)))
        expect(new Set(tops).size).toBe(1)
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
      await groups.first().evaluate(element => element.scrollIntoView({ block: 'center', inline: 'end' }))
      await page.screenshot({ path: testInfo.outputPath(`${name}-${width}.png`), animations: 'disabled' })
    })
  }
}
