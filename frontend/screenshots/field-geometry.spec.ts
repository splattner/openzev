/**
 * Field-geometry regression check: native and Mantine single-line controls
 * share one default presentation (height, type, radius, label/help order).
 *
 * Read-only: uses the seeded demo dataset, opens modals without submitting,
 * creates nothing. Run with `npm run test:browser`.
 */
import { test, expect, type Locator, type Page } from '@playwright/test'
import { navigateTo, pinDemoZev } from './helpers'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('openzev.language', 'en')
  })
  expect(await pinDemoZev(page), 'demo ZEV not found — is the stack seeded?').toBe(true)
})

async function heights(root: Locator) {
  await expect(root).toBeVisible()
  return root.evaluate((scope) => {
    const h = (el: Element) => Math.round(el.getBoundingClientRect().height * 10) / 10
    const visible = (sel: string) =>
      Array.from(scope.querySelectorAll(sel)).filter((el) => (el as HTMLElement).offsetParent !== null)
    return {
      natives: visible('input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]):not(.mantine-Input-input), select').map(h),
      // DatePickerInput renders its field as a button carrying the input
      // classes; the second button in its root is the clear control.
      mantine: visible(
        '.mantine-TextInput-input, .mantine-Autocomplete-input, .mantine-DatePickerInput-root button.mantine-Input-input',
      ).map(h),
    }
  })
}

async function modalPanel(page: Page, heading: RegExp) {
  // FormModal is nested inside the page, not portalled to body. Never fall
  // back to the document: that would accidentally measure the page behind it.
  const title = page.getByRole('heading', { name: heading, level: 2 })
  await expect(title).toBeVisible()
  return title.locator('..').locator('..')
}

function expectUniform(label: string, natives: number[], mantine: number[]) {
  expect(natives.length, `${label}: no native fields found`).toBeGreaterThan(0)
  expect(mantine.length, `${label}: no Mantine fields found`).toBeGreaterThan(0)
  for (const h of [...natives, ...mantine]) {
    expect(Math.abs(h - 44), `${label}: field height ${h}px, expected ~44px`).toBeLessThanOrEqual(1)
  }
}

test('settings general tab matches native and Mantine geometry', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (err) => errors.push(String(err)))
  await navigateTo(page, '/zev-settings/general')

  const { natives, mantine } = await heights(page.locator('main'))
  expectUniform('settings', natives, mantine)

  // Shared contract: 16px values, 16px/400 labels, 14px helpers, 12px radius.
  const css = await page.evaluate(() => {
    const cs = (sel: string, prop: keyof CSSStyleDeclaration) => {
      const el = document.querySelector(sel) as HTMLElement | null
      return el ? getComputedStyle(el)[prop] : 'missing'
    }
    return {
      labelFz: cs('.form-section .mantine-InputWrapper-label', 'fontSize'),
      labelFw: cs('.form-section .mantine-InputWrapper-label', 'fontWeight'),
      valueFz: cs('.form-section .mantine-TextInput-input', 'fontSize'),
      descFz: cs('.form-section .mantine-InputWrapper-description', 'fontSize'),
      radius: cs('.form-section .mantine-TextInput-input', 'borderRadius'),
    }
  })
  expect(css, 'field contract').toEqual({
    labelFz: '16px',
    labelFw: '400',
    valueFz: '16px',
    descFz: '14px',
    radius: '12px',
  })

  // Descriptions render below their input, never between label and input.
  const gaps = await page.getByRole('textbox', { name: 'Tariff document URL', exact: true }).evaluate((input: HTMLInputElement) => {
    const label = input.labels![0]
    const description = document.getElementById(input.getAttribute('aria-describedby')!)!
    return {
      label: input.getBoundingClientRect().top - label.getBoundingClientRect().bottom,
      help: description.getBoundingClientRect().top - input.getBoundingClientRect().bottom,
    }
  })
  expect(gaps.label).toBeCloseTo(6.4, 1)
  expect(gaps.help).toBeCloseTo(6.4, 1)
  const nativeBorder = await page.getByRole('textbox', { name: 'Name', exact: true }).evaluate(el => getComputedStyle(el).borderColor)
  await expect(page.locator('button[data-dates-input]')).toHaveCSS('border-color', nativeBorder)
  await expect(page.getByRole('textbox', { name: 'Postal code', exact: true })).toHaveCSS('border-color', nativeBorder)
  expect(errors, `pageerrors: ${errors.join(' | ')}`).toHaveLength(0)
})

test('billing tab keeps checkbox intrinsic sizing', async ({ page }) => {
  await navigateTo(page, '/zev-settings/billing')
  const boxW = await page.evaluate(() => {
    const box = document.querySelector('.checkbox-row input[type="checkbox"]') as HTMLElement | null
    return box ? Math.round(box.getBoundingClientRect().width) : -1
  })
  expect(boxW, 'checkbox not found').toBeGreaterThan(0)
  expect(boxW, 'checkbox stretched to field width').toBeLessThan(40)
})

test('vat settings rate and date fields match', async ({ page }) => {
  await navigateTo(page, '/admin/system-settings?tab=vat')
  const { natives, mantine } = await heights(page.locator('main'))
  expectUniform('vat', natives, mantine)
})

test('tariff modal fields match', async ({ page }) => {
  await navigateTo(page, '/tariffs')
  await page.getByRole('button', { name: /create tariff|new tariff/i }).first().click()
  const panel = await modalPanel(page, /create tariff|new tariff/i)
  const { natives, mantine } = await heights(panel)
  expectUniform('tariff modal', natives, mantine)
  await panel.locator('button[data-dates-input]').first().click()
  const calendar = page.getByRole('dialog')
  await expect(calendar).toBeVisible()
  await calendar.locator('td button:not([data-outside]):not([disabled])').first().click()
  await expect(calendar).toBeHidden()
})

test('wizard autocomplete opens above the modal', async ({ page }) => {
  // Overlay interaction: the ElCom suggestion dropdown must open above the
  // wizard modal (popover stacking is theme-owned; see z-layers.test.ts).
  await navigateTo(page, '/admin/zevs')
  await page.getByRole('button', { name: 'New ZEV' }).first().click()
  const panel = await modalPanel(page, /create zev/i)
  const field = panel.getByRole('combobox', { name: 'Grid operator', exact: true })
  await field.click()
  await field.fill('Stadt')
  const option = page.locator('.mantine-Autocomplete-dropdown [role="option"]').first()
  await expect(option).toBeVisible()
  const operator = await option.textContent()
  await option.click()
  await expect(field).toHaveValue(operator!)
})

test('zev create wizard fields match', async ({ page }) => {
  await navigateTo(page, '/admin/zevs')
  await page.getByRole('button', { name: 'New ZEV' }).first().click()
  const panel = await modalPanel(page, /create zev/i)
  const { natives, mantine } = await heights(panel)
  expectUniform('wizard', natives, mantine)
})

test('field states and icon spacing survive native CSS', async ({ page }) => {
  await navigateTo(page, '/zev-settings/general')
  await page.evaluate(async (fixturePath) => {
    const { mountFieldStates } = await import(/* @vite-ignore */ fixturePath)
    mountFieldStates()
  }, '/screenshots/fixtures/field-states.tsx')
  const fixture = page.locator('#field-state-fixture')
  const neutral = fixture.getByRole('textbox', { name: 'Neutral field', exact: true })
  const native = fixture.getByRole('textbox', { name: 'Native reference', exact: true })
  await expect(neutral).toBeVisible()
  const colors = await neutral.evaluate(el => {
    const probe = document.createElement('span')
    el.parentElement!.appendChild(probe)
    const resolve = (token: string) => {
      probe.style.color = `var(${token})`
      return getComputedStyle(probe).color
    }
    const result = {
      border: resolve('--border-default'),
      focus: resolve('--mantine-primary-color-filled'),
      error: resolve('--mantine-color-error'),
      success: resolve('--mantine-color-success'),
      disabled: resolve('--mantine-color-disabled'),
    }
    probe.remove()
    return result
  })
  await expect(neutral).toHaveCSS('border-color', colors.border)
  await native.focus()
  await page.keyboard.press('Tab')
  await expect(neutral).toBeFocused()
  await expect(neutral).toHaveCSS('border-color', colors.focus)
  const invalid = fixture.getByRole('textbox', { name: 'Invalid field', exact: true })
  await expect(invalid).toHaveCSS('border-color', colors.error)
  await invalid.focus()
  await expect(invalid).toHaveCSS('border-color', colors.error)
  await expect(fixture.getByRole('textbox', { name: 'Successful field', exact: true })).toHaveCSS('border-color', colors.success)
  await expect(fixture.getByRole('textbox', { name: 'Disabled field', exact: true })).toHaveCSS('background-color', colors.disabled)
  await expect(fixture.locator('button[data-dates-input]')).toHaveCSS('border-color', colors.error)
  const insets = await fixture.getByRole('textbox', { name: 'Field with icons', exact: true }).evaluate(el => {
    const css = getComputedStyle(el)
    const sectionWidth = (position: string) => el.parentElement!
      .querySelector(`[data-position="${position}"]`)!.getBoundingClientRect().width
    return {
      left: parseFloat(css.paddingLeft), right: parseFloat(css.paddingRight),
      leftSection: sectionWidth('left'), rightSection: sectionWidth('right'),
    }
  })
  expect(insets.left).toBeGreaterThanOrEqual(insets.leftSection)
  expect(insets.right).toBeGreaterThanOrEqual(insets.rightSection)
  const multiline = await fixture.getByRole('textbox', { name: 'Multiline field', exact: true }).boundingBox()
  expect(multiline!.height).toBeGreaterThan(80)
})

for (const language of ['en', 'de']) {
  test(`settings fields fit at 400px (${language})`, async ({ page }) => {
    await page.addInitScript(lang => localStorage.setItem('openzev.language', lang), language)
    await page.setViewportSize({ width: 400, height: 900 })
    await navigateTo(page, '/zev-settings/general')
    const { natives, mantine } = await heights(page.locator('main'))
    expectUniform('mobile settings', natives, mantine)
    const bounds = await page.locator('main').evaluate(el => ({
      pageWidth: document.documentElement.scrollWidth,
      viewport: innerWidth,
      fields: Array.from(el.querySelectorAll('input:not([type="hidden"]), select, button[data-dates-input]'))
        .map(field => ({ left: field.getBoundingClientRect().left, right: field.getBoundingClientRect().right })),
    }))
    expect(bounds.pageWidth).toBeLessThanOrEqual(bounds.viewport)
    for (const field of bounds.fields) {
      expect(field.left).toBeGreaterThanOrEqual(0)
      expect(field.right).toBeLessThanOrEqual(bounds.viewport)
    }
  })
}
