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

test('translated backup actions are reachable at 400px', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 400, height: 1000 })
  await page.addInitScript(() => localStorage.setItem('openzev.language', 'fr'))
  await page.route('**/api/v1/backups/destinations/', route => route.fulfill({
    json: [{ id: 'backup', name: 'Sauvegarde hebdomadaire', kind: 'local', enabled: true,
      path: '/srv/sauvegardes/hebdomadaires/production', retention_count: 3 }],
  }))
  await navigateTo(page, '/admin/system-settings?tab=backup')
  const row = page.getByRole('row').filter({ hasText: 'Sauvegarde hebdomadaire' })
  await row.getByRole('button', { name: /Modifier.*Sauvegarde/ }).focus()
  await page.keyboard.press('Tab')
  await expect(row.getByRole('button', { name: /Tester/ })).toBeFocused()
  await page.keyboard.press('Tab')
  const last = row.getByRole('button', { name: /Supprimer.*Sauvegarde/ })
  await expect(last).toBeFocused()
  await expect(last).toBeInViewport({ ratio: 1 })
  await page.screenshot({ path: testInfo.outputPath('backup-actions-fr-400.png') })
})

for (const width of [400, 850]) {
  test(`OAuth row actions scroll into reach at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.addInitScript(() => localStorage.setItem('openzev.language', 'fr'))
    await page.route('**/api/v1/auth/oauth/providers/config/', route => route.fulfill({
      json: [{ id: 1, display_name: 'Fournisseur de démonstration', name: 'demo', enabled: true,
        client_id: 'my-long-production-client-id-0123456789'.repeat(3),
        redirect_url: 'https://example.test/authentication/long-callback/for-production',
        scope: 'openid email profile' }],
    }))
    await navigateTo(page, '/admin/system-settings?tab=oauth')
    const row = page.getByRole('row').filter({ hasText: 'Fournisseur de démonstration' })
    await row.getByRole('button', { name: /Modifier.*Fournisseur/ }).focus()
    await page.keyboard.press('Tab')
    const last = row.getByRole('button', { name: /Supprimer.*Fournisseur/ })
    await expect(last).toBeFocused()
    await expect(last).toBeInViewport({ ratio: 1 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}
