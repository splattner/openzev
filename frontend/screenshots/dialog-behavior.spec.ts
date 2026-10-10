import { expect, test } from '@playwright/test'
import { mockApi } from './page-anatomy-fixtures'
import { mountDialogFixture } from './dialog-fixture-helpers'

test.use({ storageState: { cookies: [], origins: [] } })

for (const language of ['en', 'de']) {
  test(`email history wraps long content and fits desktop and mobile (${language})`, async ({ page }, testInfo) => {
    const errors = await mockApi(page, { populated: true })
    await page.addInitScript(lang => localStorage.setItem('openzev.language', lang), language)
    await page.route('**/invoices/invoices/1/', route => route.fulfill({ json: { email_logs: [{
      id: 'log1', invoice: '1', recipient: `${'long-recipient-'.repeat(4)}@example.test`,
      subject: 'Invoice subject '.repeat(6), status: 'failed', error_message: 'SMTP_error_'.repeat(20),
      created_at: '2026-10-01T10:00:00Z', sent_at: null,
    }] } }))
    await page.goto('/billing/emails')
    const opener = page.locator('.billing-workflow-table tbody button').first()
    await opener.focus()
    await page.keyboard.press('Enter')
    const history = page.getByRole('dialog', { name: /R-1/ })
    await expect(history).toBeFocused()
    await expect(history.locator('.email-log-recipient')).toContainText('long-recipient-')
    await expect(history.locator('.email-log-subject')).toContainText('Invoice subject')
    await expect(history.locator('.email-log-error')).toBeVisible()
    await expect(history.locator('.email-log-error')).toContainText('SMTP_error_')
    for (const width of [1440, 400]) {
      await page.setViewportSize({ width, height: 900 })
      // The sheet's header runs edge to edge, so the sheet has no top inset.
      await expect(history).toHaveCSS('padding', width === 400 ? '0px 16px 16px' : '0px 28px 28px')
      expect(await history.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`email-history-${language}-${width}.png`) })
    }
    if (language === 'en') {
      await history.focus()
      await page.keyboard.press('Shift+Tab')
      await expect(history.locator('.email-logs-footer button')).toBeFocused()
      await page.keyboard.press('Tab')
      await expect(history.locator('.form-modal-close')).toBeFocused()
    }
    await page.keyboard.press('Escape')
    await expect(history).toHaveCount(0)
    await expect(opener).toBeFocused()
    expect(errors).toEqual([])
  })
}

test('an earlier DOM sibling opens above the existing modal and owns keyboard and scrim', async ({ page }, testInfo) => {
  const errors = await mockApi(page, { populated: true })
  await page.goto('/billing/emails')
  await page.locator('.billing-workflow-table tbody button').first().click()
  const history = page.getByRole('dialog', { name: 'Email History – Invoice R-1', exact: true })
  await expect(history).toBeVisible()
  await mountDialogFixture(page)
  const form = page.getByRole('dialog', { name: 'Fixture form', exact: true })
  const opener = form.getByRole('button', { name: 'Open confirmation' })
  await opener.click()
  const confirmation = page.getByRole('dialog', { name: 'Fixture confirmation', exact: true })
  await expect(confirmation).toBeFocused()
  await test.step('Opening order controls the visual stack', async () => {
    const panelColor = await confirmation.evaluate(el => {
      const probe = document.createElement('span')
      probe.style.color = 'var(--surface-card)'
      el.append(probe)
      const color = getComputedStyle(probe).color
      probe.remove()
      return color
    })
    await expect(confirmation).toHaveCSS('background-color', panelColor)
    expect(await confirmation.evaluate(el => {
      const scrim = el.parentElement!
      const below = scrim.nextElementSibling!
      return scrim.compareDocumentPosition(below) & Node.DOCUMENT_POSITION_FOLLOWING
        && Number(getComputedStyle(scrim).zIndex) > Number(getComputedStyle(below).zIndex)
        && document.elementFromPoint(1, 1) === scrim
    })).toBeTruthy()
  })
  await test.step('Only the top scrim dismisses its dialog', async () => {
    await form.locator('..').evaluate(el => (el as HTMLElement).click())
    await expect(confirmation).toBeVisible()
    await page.mouse.click(1, 1)
    await expect(confirmation).toHaveCount(0)
    await expect(opener).toBeFocused()
  })

  await opener.click()
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(confirmation).toHaveCSS('padding', width === 400 ? '16px' : '32px')
    await page.screenshot({ path: testInfo.outputPath(`confirmation-${width}.png`) })
  }
  await test.step('Pending keyboard dismissal restores the remaining stack', async () => {
    await confirmation.focus()
    await page.keyboard.press('Shift+Tab')
    await expect(confirmation.locator('button').last()).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(confirmation.locator('button').last()).toBeDisabled()
    await expect(confirmation.getByRole('status')).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('confirmation-processing-mobile.png') })
    await page.keyboard.press('Tab')
    await expect(confirmation.getByRole('button', { name: /Close|Schliessen/ })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(confirmation).toHaveCount(0)
    await expect(opener).toBeFocused()
    await expect(history).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(form).toHaveCount(0)
    await expect(history).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(history).toHaveCount(0)
  })
  expect(errors).toEqual([])
})

test('Tab skips hidden, inert, disabled-fieldset and negative-tabindex controls', async ({ page }) => {
  const errors = await mockApi(page, { populated: true })
  await page.goto('/billing/emails')
  await mountDialogFixture(page, 'tabbability')
  const dialog = page.getByRole('dialog', { name: 'Fixture form', exact: true })
  const action = dialog.getByRole('button', { name: 'Real action' })
  await expect(dialog).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(action).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(dialog.locator('.form-modal-close')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(action).toBeFocused()
  expect(errors).toEqual([])
})
