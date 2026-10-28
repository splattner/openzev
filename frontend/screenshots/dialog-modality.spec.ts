import { expect, test, type Page } from '@playwright/test'
import { mockApi } from './page-anatomy-fixtures'
import { mountDialogFixture } from './dialog-fixture-helpers'

test.use({ storageState: { cookies: [], origins: [] } })

async function mount(page: Page, scene: 'stack' | 'nested' | 'simultaneous' | 'portals', strict = false) {
  const errors = await mockApi(page, { populated: true })
  await page.goto('/billing/emails')
  await mountDialogFixture(page, scene, strict)
  return errors
}

for (const scene of ['stack', 'nested'] as const) {
  test(`only the active ${scene} dialog is interactive and exposed as modal`, async ({ page }, testInfo) => {
    const errors = await mount(page, scene)
    await page.setViewportSize({ width: 400, height: 900 })
    const lower = page.getByRole('dialog', { name: 'Fixture form', exact: true, includeHidden: true })
    const opener = lower.getByRole('button', { name: 'Open confirmation', includeHidden: true })
    await opener.click()
    const top = page.getByRole('dialog', { name: 'Fixture confirmation', exact: true })
    await expect(top).toBeFocused()
    await expect(page.locator('[role=dialog][aria-modal=true]')).toHaveCount(1)
    expect(await top.evaluate(el => !!el.closest('[inert]'))).toBe(false)
    expect(await opener.evaluate(el => !!el.closest('[inert]'))).toBe(true)
    await lower.focus()
    await expect(top).toBeFocused()
    const ax = await (await page.context().newCDPSession(page)).send('Accessibility.getFullAXTree')
    expect(ax.nodes.filter(node => !node.ignored && node.properties?.some(property => property.name === 'modal' && property.value.value === true))
      .map(node => node.name?.value)).toEqual(['Fixture confirmation'])
    await page.screenshot({ path: testInfo.outputPath(`modal-${scene}-400.png`) })
    await page.keyboard.press('Escape')
    await expect(top).toHaveCount(0)
    await expect(opener).toBeFocused()
    await expect(lower).toHaveAttribute('aria-modal', 'true')
    await page.keyboard.press('Escape')
    await expect(lower).toHaveCount(0)
    const background = page.locator('.billing-workflow-table tbody button').first()
    expect(await background.evaluate(el => !!el.closest('[inert]'))).toBe(false)
    await background.focus()
    await expect(background).toBeFocused()
    expect(errors).toEqual([])
  })
}

test('popup portals inside a dialog retain selection, calendar and keyboard interaction', async ({ page }) => {
  const errors = await mount(page, 'portals')
  const dialog = page.getByRole('dialog', { name: 'Fixture form', exact: true })
  const choice = dialog.getByRole('combobox', { name: 'Fixture choice' })
  await choice.click()
  const option = page.getByRole('option', { name: 'Two', exact: true })
  await expect(option).toBeVisible()
  expect(await option.evaluate(el => !!el.closest('[inert]'))).toBe(false)
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(choice).toHaveValue('Two')
  await dialog.getByRole('button', { name: 'Fixture date' }).click()
  const day = page.getByRole('button', { name: '15 October 2026', exact: true })
  await expect(day).toBeVisible()
  expect(await day.evaluate(el => !!el.closest('[inert]'))).toBe(false)
  await day.focus()
  await expect(day).toBeFocused()
  await page.keyboard.press('Tab')
  expect(await page.evaluate(() => !!document.activeElement?.closest('[inert]'))).toBe(false)
  await day.click()
  await expect(dialog.getByRole('button', { name: 'Fixture date' })).toContainText('October 15, 2026')
  // The picked option and date are unsaved input: Escape asks before closing.
  await page.keyboard.press('Escape')
  const discard = page.getByRole('dialog', { name: 'Discard changes?', exact: true })
  await expect(discard).toBeVisible()
  await discard.getByRole('button', { name: 'Discard', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(errors).toEqual([])
})

test('new background content becomes inert without suppressing global feedback', async ({ page }) => {
  const errors = await mount(page, 'stack')
  await page.evaluate(() => {
    const button = document.createElement('button')
    button.id = 'late-background-control'
    button.textContent = 'Background'
    document.body.append(button)
  })
  const background = page.locator('#late-background-control')
  await expect(background).toHaveAttribute('inert', '')
  await background.focus()
  await expect(page.getByRole('dialog', { name: 'Fixture form', exact: true })).toBeFocused()
  await expect(page.locator('.toast-stack').first()).toHaveAttribute('aria-live', 'polite')
  expect(await page.locator('.toast-stack').first().evaluate(el => !!el.closest('[inert]'))).toBe(false)
  await page.keyboard.press('Escape')
  expect(await background.evaluate(el => el.hasAttribute('inert'))).toBe(false)
  expect(errors).toEqual([])
})

for (const strict of [false, true]) {
  test(`simultaneous nested opening keeps the child active, StrictMode=${strict}`, async ({ page }) => {
    const errors = await mount(page, 'simultaneous', strict)
    const parent = page.getByRole('dialog', { name: 'Fixture form', exact: true, includeHidden: true })
    const child = page.getByRole('dialog', { name: 'Fixture child', exact: true })
    await expect(child).toBeFocused()
    await expect(child).toHaveAttribute('aria-modal', 'true')
    await expect(parent).not.toHaveAttribute('aria-modal', 'true')
    expect(await child.evaluate(el => !!el.closest('[inert]'))).toBe(false)
    expect(await parent.getByRole('button', { name: 'Open confirmation', includeHidden: true }).evaluate(el => !!el.closest('[inert]'))).toBe(true)
    expect(await child.evaluate(el => Number(getComputedStyle(el.parentElement!).zIndex)
      > Number(getComputedStyle(el.closest('.dialog-scrim')!.parentElement!.closest('.dialog-scrim')!).zIndex))).toBe(true)
    await page.keyboard.press('Escape')
    await expect(child).toHaveCount(0)
    await expect(parent).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(parent).toHaveCount(0)
    expect(errors).toEqual([])
  })
}

for (const [widget, focus] of [
  ['select', 'trigger'], ['calendar', 'popup'], ['menu', 'popup'],
  ['calendar', 'trigger'], ['menu', 'trigger'],
] as const) {
  test(`Escape closes the ${widget} popup before the dialog, focus=${focus}`, async ({ page }) => {
    const errors = await mount(page, 'portals')
    const dialog = page.getByRole('dialog', { name: 'Fixture form', exact: true })
    const trigger = widget === 'select'
      ? dialog.getByRole('combobox', { name: 'Fixture choice' })
      : dialog.getByRole('button', { name: widget === 'calendar' ? 'Fixture date' : 'Fixture menu' })
    const popupControl = widget === 'select' ? page.getByRole('option', { name: 'Two', exact: true })
      : widget === 'calendar' ? page.getByRole('button', { name: '15 October 2026', exact: true })
        : page.getByRole('menuitem', { name: 'Fixture action', exact: true })
    await trigger.click()
    await expect(popupControl).toBeVisible()
    await (focus === 'trigger' ? trigger : popupControl).focus()
    await page.keyboard.press('Escape')
    await expect(popupControl).toBeHidden()
    await expect(dialog).toBeVisible()
    if (focus === 'trigger') await expect(trigger).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    expect(errors).toEqual([])
  })
}

test('invalid popup ancestor references cannot expose background controls', async ({ page }) => {
  const errors = await mount(page, 'stack')
  await page.evaluate(() => {
    const host = document.getElementById('confirmation-fixture')!
    const background = document.createElement('button')
    background.id = 'ancestor-background'
    background.textContent = 'Background'
    host.append(background)
    document.body.id = 'fixture-body'
    document.documentElement.id = 'fixture-document'
    host.querySelector('button')!.setAttribute('aria-controls', 'confirmation-fixture fixture-body fixture-document')
  })
  const background = page.locator('#ancestor-background')
  await expect.poll(() => background.evaluate(el => !!el.closest('[inert]'))).toBe(true)
  await background.focus()
  await expect(page.getByRole('dialog', { name: 'Fixture form', exact: true })).toBeFocused()
  expect(errors).toEqual([])
})

test('announcement-only toast controls stay outside the dialog Tab cycle', async ({ page }) => {
  const errors = await mount(page, 'portals')
  const dialog = page.getByRole('dialog', { name: 'Fixture form', exact: true })
  await page.evaluate(() => {
    for (const stack of document.querySelectorAll('.toast-stack')) {
      const action = document.createElement('button')
      action.textContent = 'Toast action'
      stack.append(action)
    }
  })
  const first = dialog.locator('.form-modal-close')
  const last = dialog.getByRole('button', { name: 'Fixture menu' })
  await dialog.focus()
  await page.keyboard.press('Shift+Tab')
  await expect(last).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(first).toBeFocused()
  for (const control of [dialog.getByRole('combobox', { name: 'Fixture choice' }),
    dialog.getByRole('button', { name: 'Fixture date' }), last]) {
    await page.keyboard.press('Tab')
    await expect(control).toBeFocused()
  }
  await page.keyboard.press('Tab')
  await expect(first).toBeFocused()
  expect(errors).toEqual([])
})
