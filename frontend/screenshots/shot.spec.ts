/**
 * One-off screenshot capture for release notes.
 *
 * Unlike `capture.spec.ts`, which owns a fixed set of user-guide shots that are
 * regenerated as the UI moves, this takes a single arbitrary shot on demand.
 * Release-note images are frozen at the version they document — re-running a
 * 1.9.0 capture against a 2027 UI would illustrate the note with a product
 * that release never shipped — so there is deliberately no per-release spec
 * accumulating here. Take the shot, commit the PNG, forget the command.
 *
 * Run (from `frontend/`):
 *
 *   SHOT_NAME=1.9.0-bands-after SHOT_URL=/invoices npm run shot
 *
 * Options (environment variables):
 *   SHOT_NAME      required — output filename stem, conventionally
 *                  `<version>-<slug>[-before|-after]`
 *   SHOT_URL       required — app path to open, e.g. `/invoices`
 *   SHOT_SELECTOR  crop to this element's box instead of the page. Usually
 *                  what a release note wants: the table that changed, not
 *                  1400px of chrome around it.
 *   SHOT_MODE      `full` (default, grows the viewport to the content) or
 *                  `viewport`. Ignored when SHOT_SELECTOR is set.
 *   SHOT_DIR       output directory (default docs/release-notes/screenshots)
 *   SHOT_WAIT      extra settle milliseconds before the shot (default 0)
 *   SHOT_LANG      UI language (de/fr/it/en). Defaults to `en`, because the
 *                  release notes are written in English and a German
 *                  screenshot in an English paragraph reads as a mistake.
 *   SHOT_NO_PIN    set to skip pinning the demo ZEV
 *
 * The connection and credential variables are the ones `capture.spec.ts` uses
 * (SCREENSHOT_BASE_URL, SCREENSHOT_API_URL, SCREENSHOT_USER, ...).
 */
import { test, expect, type Page } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'
import {
  loginViaAPI,
  navigateTo,
  pinDemoZev,
  resetHover,
  screenshotFull,
  screenshotViewport,
} from './helpers'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const NAME = process.env.SHOT_NAME
const URL_PATH = process.env.SHOT_URL
const SELECTOR = process.env.SHOT_SELECTOR
const MODE = process.env.SHOT_MODE ?? 'full'
const WAIT = Number(process.env.SHOT_WAIT ?? 0)
const LANG = process.env.SHOT_LANG ?? 'en'
const DIR = process.env.SHOT_DIR
  ? path.resolve(process.env.SHOT_DIR)
  : path.resolve(__dirname, '../../docs/release-notes/screenshots')

/** Crop to one element — the padding keeps a card's own shadow in frame. */
async function screenshotElement(page: Page, dir: string, name: string, selector: string) {
  await resetHover(page)
  const target = page.locator(selector).first()
  await expect(target, `SHOT_SELECTOR matched nothing: ${selector}`).toBeVisible()
  await target.screenshot({ path: path.join(dir, `${name}.png`) })
}

test('shot', async ({ page }) => {
  expect(NAME, 'SHOT_NAME is required').toBeTruthy()
  expect(URL_PATH, 'SHOT_URL is required').toBeTruthy()

  await loginViaAPI(page)
  await page.addInitScript((lang: string) => {
    localStorage.setItem('openzev.language', lang)
  }, LANG)
  if (!process.env.SHOT_NO_PIN) {
    // Loud rather than silent: a shot of an empty tenant looks like a working
    // capture of a broken feature, and that is what ends up in the notes.
    expect(await pinDemoZev(page), 'demo ZEV not found — is the stack seeded?').toBe(true)
  }
  await navigateTo(page, URL_PATH!)
  if (WAIT) await page.waitForTimeout(WAIT)

  if (SELECTOR) {
    await screenshotElement(page, DIR, NAME!, SELECTOR)
  } else if (MODE === 'viewport') {
    await screenshotViewport(page, DIR, NAME!)
  } else {
    await screenshotFull(page, DIR, NAME!)
  }
  console.log(`\n  wrote ${path.join(DIR, `${NAME}.png`)}\n`)
})
