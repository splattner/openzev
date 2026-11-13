import { expect, test, type Page, type Request } from '@playwright/test'
import { mockApi } from './page-anatomy-fixtures'

test.use({ storageState: { cookies: [], origins: [] } })

async function holdResponse(page: Page, url: string, status: number, json: unknown) {
  let complete!: () => void, dispatched!: () => void, request: Request | undefined
  const pending = new Promise<void>(resolve => { complete = resolve })
  const started = new Promise<void>(resolve => { dispatched = resolve })
  await page.route(url, async route => {
    request = route.request()
    dispatched()
    await pending
    await route.fulfill({ status, json })
  })
  return { started, complete, get request() { return request! } }
}

async function expectReportedFailure(page: Page, message: string, errors: string[]) {
  await expect(page.locator('.toast-error')).toHaveCount(1)
  await expect(page.locator('.toast-error')).toContainText(message)
  expect(errors.filter(error => !error.includes('the server responded with a status of 400'))).toEqual([])
}

for (const dismiss of [false, true]) {
  test(`participant unlink failure reports once, dismissed=${dismiss}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: dismiss ? 400 : 1440, height: 900 })
    const errors = await mockApi(page, { populated: true })
    const operation = await holdResponse(page, '**/zev/participants/p42/unlink-account/', 400, { detail: 'Unlink failed' })
    await page.goto('/participants')
    const trigger = page.locator('main').getByRole('button', { name: 'More', exact: true })
    await trigger.click()
    await page.getByRole('menuitem', { name: 'Unlink', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Unlink account?' })
    await dialog.getByRole('button', { name: 'Unlink', exact: true }).click()
    await operation.started
    expect(operation.request.method()).toBe('POST')
    if (dismiss) {
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await trigger.click()
      await expect(page.getByRole('menuitem', { name: 'Unlink', exact: true })).toBeDisabled()
      await page.keyboard.press('Escape')
    }
    operation.complete()
    await expect(dialog).toHaveCount(0)
    await expectReportedFailure(page, 'Unlink failed', errors)
    await page.screenshot({ path: testInfo.outputPath('unlink-failure.png'), fullPage: true })
    await trigger.click()
    await expect(page.getByRole('menuitem', { name: 'Unlink', exact: true })).toBeEnabled()
  })

  test(`invoice-link failure reports once, dismissed=${dismiss}`, async ({ page }) => {
    const errors = await mockApi(page, { populated: true })
    await page.route('**/invoices/invoices/1/', route => route.fulfill({ json: {
      id: '1', invoice_number: 'R-1', zev: '42', zev_name: 'Review ZEV', participant_name: 'Participant A',
      period_start: '2026-09-01', period_end: '2026-09-30', status: 'sent', total_chf: '10.00', pdf_url: null,
      access_link: { prefix: 'abcdefgh', created_at: '2026-09-01T00:00:00Z', last_used_at: null },
    } }))
    const operation = await holdResponse(page, '**/invoices/invoices/1/revoke-access/', 400, { detail: 'Revocation failed' })
    await page.goto('/billing/invoices/1')
    const trigger = page.getByRole('button', { name: 'Revoke link', exact: true })
    await trigger.click()
    const dialog = page.getByRole('dialog', { name: 'Revoke this access link?' })
    await dialog.getByRole('button', { name: 'Revoke link', exact: true }).click()
    await operation.started
    if (dismiss) {
      await dialog.getByRole('button', { name: 'Close', exact: true }).click()
      await expect(dialog).toHaveCount(0)
      await expect(page.locator('main h1')).toBeFocused()
    }
    await expect(trigger).toBeDisabled()
    operation.complete()
    await expect(dialog).toHaveCount(0)
    await expect(trigger).toBeEnabled()
    await expectReportedFailure(page, 'Revocation failed', errors)
  })

  test(`deactivation failure reports once without an edit form, dismissed=${dismiss}`, async ({ page }) => {
    const errors = await mockApi(page, { populated: true })
    const operation = await holdResponse(page, '**/auth/users/2/', 400, { detail: 'Deactivation failed' })
    await page.goto('/admin/accounts/users')
    await page.locator('main').getByRole('button', { name: 'More: account@example.test', exact: true }).click()
    await page.getByRole('menuitem', { name: 'Deactivate', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Deactivate account?' })
    await dialog.getByRole('button', { name: 'Deactivate', exact: true }).click()
    await operation.started
    if (dismiss) await page.keyboard.press('Escape')
    operation.complete()
    await expect(dialog).toHaveCount(0)
    await expectReportedFailure(page, 'Deactivation failed', errors)
  })

  test(`ZEV purge retains submitted inputs and reports once, dismissed=${dismiss}`, async ({ page }) => {
    const errors = await mockApi(page, { populated: true, zevs: [{ id: '42', name: 'Disabled ZEV', disabled_at: '2026-10-01T00:00:00Z' }] })
    const operation = await holdResponse(page, '**/zev/zevs/42/purge/', 400, { detail: 'Purge failed' })
    await page.goto('/admin/zevs')
    const trigger = page.getByRole('button', { name: 'Purge', exact: true })
    await trigger.click()
    const dialog = page.getByRole('dialog', { name: 'Permanently delete ZEV' })
    await dialog.getByRole('textbox').fill('Disabled ZEV')
    await dialog.getByRole('button', { name: 'Permanently delete', exact: true }).click()
    await operation.started
    await dialog.getByRole('textbox').fill('Changed after submission')
    if (dismiss) await page.keyboard.press('Escape')
    await expect(trigger).toBeDisabled()
    expect(operation.request.postDataJSON()).toEqual({ confirm_name: 'Disabled ZEV' })
    operation.complete()
    await expect(dialog).toHaveCount(0)
    await expect(trigger).toBeEnabled()
    await expectReportedFailure(page, 'Purge failed', errors)
  })

  for (const action of ['enable', 'disable']) {
    test(`ZEV ${action} failure reports once, dismissed=${dismiss}`, async ({ page }) => {
      const errors = await mockApi(page, { populated: true, zevs: [{
        id: '42', name: 'Review ZEV', disabled_at: action === 'enable' ? '2026-10-01T00:00:00Z' : null,
      }] })
      const operation = await holdResponse(page, `**/zev/zevs/42/${action}/`, 400, { detail: 'ZEV action failed' })
      await page.goto('/admin/zevs')
      const label = action === 'enable' ? 'Enable' : 'Disable'
      const trigger = page.locator('main').getByRole('button', { name: label, exact: true })
      await trigger.click()
      const dialog = page.getByRole('dialog', { name: `${label} ZEV` })
      await dialog.getByRole('button', { name: `${label} ZEV`, exact: true }).click()
      await operation.started
      if (dismiss) await page.keyboard.press('Escape')
      await expect(trigger).toBeDisabled()
      operation.complete()
      await expect(dialog).toHaveCount(0)
      await expect(trigger).toBeEnabled()
      await expectReportedFailure(page, 'ZEV action failed', errors)
    })
  }

  for (const mode of ['clear', 'delete']) {
    test(`dynamic-source ${mode} retains submitted inputs and reports once, dismissed=${dismiss}`, async ({ page }) => {
      const errors = await mockApi(page)
      await page.route('**/tariffs/dynamic-sources/', route => route.fulfill({ json: [{
        id: 's1', label: 'Operator source', url: 'https://example.test/prices', api_version: 'v1_0_5',
        tariff_type: 'grid', enabled: true, last_fetch_status: 'ok', point_count: 12,
        linked_tariff_count: 0, linked_zev_count: 0, supports_backfill: true,
      }] }))
      const url = mode === 'clear' ? '**/tariffs/dynamic-sources/s1/prices/' : '**/tariffs/dynamic-sources/s1/'
      const operation = await holdResponse(page, url, 400, { detail: 'Source operation failed' })
      await page.goto('/admin/dynamic-sources')
      const action = mode === 'clear' ? 'Clear fetched prices' : 'Delete source'
      const trigger = page.getByRole('button', { name: 'Actions: Operator source', exact: true })
      await trigger.click()
      await page.getByRole('menuitem', { name: action, exact: true }).click()
      const dialog = page.getByRole('dialog', { name: mode === 'clear' ? action : 'Delete dynamic price source' })
      await dialog.getByRole('textbox').fill('Operator source')
      await dialog.getByRole('button', { name: action, exact: true }).click()
      await operation.started
      await dialog.getByRole('textbox').fill('Changed after submission')
      if (dismiss) {
        await dialog.getByRole('button', { name: 'Close', exact: true }).click()
        await trigger.click()
        await expect(page.getByRole('menuitem', { name: action, exact: true })).toBeDisabled()
        await page.keyboard.press('Escape')
      }
      expect(operation.request.method()).toBe('DELETE')
      expect(operation.request.postDataJSON()).toEqual({ confirmation: 'Operator source' })
      operation.complete()
      await expect(dialog).toHaveCount(0)
      await expectReportedFailure(page, 'Source operation failed', errors)
      await trigger.click()
      await expect(page.getByRole('menuitem', { name: action, exact: true })).toBeEnabled()
    })
  }
}

test('dismissed deactivation cannot clear an account edit opened while it was pending', async ({ page }) => {
  const errors = await mockApi(page, { populated: true })
  const operation = await holdResponse(page, '**/auth/users/2/', 200, { id: 2, is_active: false })
  await page.goto('/admin/accounts/users')
  await page.locator('main').getByRole('button', { name: 'More: account@example.test', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Deactivate', exact: true }).click()
  await page.getByRole('dialog', { name: 'Deactivate account?' }).getByRole('button', { name: 'Deactivate', exact: true }).click()
  await operation.started
  await page.keyboard.press('Escape')
  await page.locator('main').getByRole('button', { name: 'Edit: account@example.test', exact: true }).click()
  const edit = page.getByRole('dialog', { name: 'Edit account', exact: true })
  const username = edit.getByRole('textbox', { name: 'Username', exact: true })
  await username.fill('retained-draft')
  operation.complete()
  await expect(page.locator('.toast-success')).toBeVisible()
  await expect(edit).toBeVisible()
  await expect(username).toHaveValue('retained-draft')
  expect(errors).toEqual([])
})
