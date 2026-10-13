import { expect, test } from '@playwright/test'
import { impersonateDemoParticipant, navigateTo, pinDemoZev } from './helpers'

for (const width of [1440, 400]) {
  test(`metering table semantics and keyboard editors at ${width}px`, async ({ page }, testInfo) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('console', message => {
      // The existing energy-data endpoint returns 404 while its feature is disabled.
      if (message.location().url.endsWith('/supplementary/sources/eligible/') && message.text().includes('404')) return
      if (message.type() === 'error') errors.push(`${message.text()} ${message.location().url}`)
    })
    await page.setViewportSize({ width, height: 900 })
    await page.addInitScript(() => localStorage.setItem('openzev.language', 'de'))
    expect(await pinDemoZev(page)).toBe(true)
    await navigateTo(page, '/metering/points?sort=last_reading')

    const table = page.getByRole('table').first()
    await expect(table).toBeVisible()
    const snapshot = await table.ariaSnapshot()
    for (const header of ['Messpunkt', 'Zuweisung', 'Letzter Messwert', 'Aktionen']) {
      expect(snapshot).toContain(`columnheader "${header}"`)
    }
    expect(snapshot).toContain('rowgroup:')
    expect(snapshot).toContain('cell')
    await expect(table.getByRole('columnheader')).toHaveCount(4)
    const row = table.locator('.metering-point-row').filter({ has: page.locator('.metering-holder-name') }).first()
    await expect(row.getByRole('cell')).toHaveCount(4)
    const meterId = (await row.locator('.metering-point-id-main strong').innerText()).trim()
    expect(snapshot).toContain(meterId)

    await expect(row.locator('.metering-point-id-main button, .metering-holder-name button')).toHaveCount(0)
    const pointMenu = row.getByRole('button', { name: `Aktionen für ${meterId}`, exact: true })
    await pointMenu.focus()
    await pointMenu.press('Enter')
    const pointEdit = page.getByRole('menuitem', { name: 'Bearbeiten', exact: true })
    await pointEdit.focus()
    await pointEdit.press('Enter')
    await expect(page.getByRole('dialog').getByLabel('Messpunkt-ID *', { exact: true })).toHaveValue(meterId)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(pointMenu).toBeFocused()

    const participantName = (await row.locator('.metering-holder-name').innerText()).trim()
    await row.locator('.metering-point-expand').click()
    const assignmentPeriod = await table.locator('.metering-assignment-main > .muted').first().innerText()
    const [assignmentFrom, assignmentTo] = assignmentPeriod.split(' – ')
    const assignmentEdit = table.locator('.metering-assignment-row').first().getByRole('button', { name: 'Bearbeiten', exact: true })
    await assignmentEdit.focus()
    await assignmentEdit.press('Enter')
    await expect(page.getByRole('dialog').getByRole('combobox', { name: 'Teilnehmer *', exact: true }).locator('option:checked')).toHaveText(participantName)
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Gültig ab *', exact: true })).toHaveText(assignmentFrom)
    await expect(page.getByRole('dialog').getByRole('button', { name: 'Gültig bis', exact: true })).toHaveText(assignmentTo === 'Offen' ? '' : assignmentTo)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(assignmentEdit).toBeFocused()
    await row.locator('.metering-point-expand').click()

    const building = table.locator('..').locator('.building-header')
    const buildingEdit = building.getByRole('button', { name: 'Gebäude bearbeiten', exact: true })
    const buildingName = await building.getByRole('heading').innerText()
    await buildingEdit.focus()
    await buildingEdit.press('Enter')
    await expect(page.getByRole('dialog').getByRole('textbox', { name: /^Name/ })).toHaveValue(buildingName)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(buildingEdit).toBeFocused()

    const attention = page.getByRole('button', { name: /^Handlungsbedarf/ })
    await expect(attention).toBeVisible()
    const count = Number((await attention.innerText()).match(/\d+/)![0])
    const attentionRows = page.locator('.metering-point-row').filter({ has: page.locator('.metering-quality-issue, .metering-holder-issue') })
    await expect(attentionRows).toHaveCount(count)
    await attention.click()
    await expect(page).toHaveURL(/view=attention/)
    await expect(page).toHaveURL(/sort=last_reading/)
    await expect(page.locator('.metering-point-row')).toHaveCount(count)
    await expect(attentionRows).toHaveCount(count)
    await attention.click()
    await expect(page).not.toHaveURL(/view=attention/)
    await table.getByRole('button', { name: `Details zu ${meterId} anzeigen`, exact: true }).click()
    const detail = table.locator('.metering-point-detail')
    await expect(detail).toHaveAttribute('colspan', '4')
    expect(await table.ariaSnapshot()).toContain('heading "Messung"')
    await expect(detail.locator('a[href*="tab=quality"]')).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath(`metering-${width}.png`), fullPage: true })
    expect(errors).toEqual([])
  })
}

for (const width of [1440, 1024, 900, 800, 769, 761, 760, 400]) {
  test(`metering sheet geometry with long identifiers and names at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await page.addInitScript(() => {
      localStorage.setItem('openzev.language', 'de')
      localStorage.setItem('openzev.sidebarCollapsed', 'false')
    })
    // Exercise the same layout using long source identifiers/names without changing demo data.
    await page.route(/\/api\/v1\/zev\/metering-points\/(?:\?.*)?$/, async route => {
      const response = await route.fetch()
      const body = await response.json()
      for (const [index, point] of body.results.entries()) point.meter_id = `CH123456789012345678901234567890${String(index).padStart(3, '0')}`
      await route.fulfill({ response, json: body })
    })
    await page.route('**/api/v1/zev/participants/**', async route => {
      const response = await route.fetch()
      const body = await response.json()
      for (const participant of body.results) {
        participant.first_name = 'Alexandra'
        participant.last_name = 'SchneiderMüllerMitEinemSehrLangenUnunterbrochenenFamiliennamen'
      }
      await route.fulfill({ response, json: body })
    })
    expect(await pinDemoZev(page)).toBe(true)
    await navigateTo(page, '/metering/points')
    const table = page.getByRole('table').first()
    const row = table.locator('.metering-point-row').first()
    await expect(row.locator('.metering-point-id-main strong')).toHaveText(/^CH123456789012345678901234567890\d{3}$/)
    await expect(row.locator('.metering-holder-name')).toContainText('Alexandra')
    await row.locator('.metering-point-expand').click()
    await expect(table.locator('.metering-point-detail')).toBeVisible()
    await expect.poll(async () => {
      const detail = await table.locator('.metering-point-detail').boundingBox()
      const bounds = await table.boundingBox()
      return Math.abs(detail!.width - bounds!.width)
    }).toBeLessThanOrEqual(2)
    await expect.poll(() => page.locator('.metering-sheet').evaluateAll(sheets => sheets.every(sheet => {
      const bounds = sheet.getBoundingClientRect()
      return [...sheet.querySelectorAll('.metering-point-row button, .metering-point-row a, .metering-point-detail button, .metering-point-detail a, .metering-holder-name, .metering-assignment-main')].every(control => {
        const box = control.getBoundingClientRect()
        return box.left >= bounds.left && box.right <= bounds.right && control.scrollWidth <= control.clientWidth
      })
    }))).toBe(true)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`metering-layout-${width}.png`), fullPage: true })
  })
}

test('participant tables expose three columns and expanded measurement details', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('openzev.language', 'de'))
  await impersonateDemoParticipant(page)
  await navigateTo(page, '/metering/points')
  const table = page.getByRole('table').first()
  await expect(table).toBeVisible()
  await expect(table.getByRole('columnheader')).toHaveCount(3)
  const row = table.locator('.metering-point-row').first()
  await expect(row.getByRole('cell')).toHaveCount(3)
  await expect(row.getByRole('button', { name: /bearbeiten/ })).toHaveCount(0)
  await row.locator('.metering-point-expand').click()
  await expect(table.locator('.metering-point-detail')).toHaveAttribute('colspan', '3')
  const snapshot = await table.ariaSnapshot()
  expect(snapshot).toContain('heading "Messung"')
  expect(snapshot).not.toContain('columnheader "Zuweisung"')
})
