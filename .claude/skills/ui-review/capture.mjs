#!/usr/bin/env node
/**
 * Screenshot capture for a UI/UX review.
 *
 * Signs in as each seeded demo persona, opens every planned screen at every
 * planned width and language, optionally runs a few interaction steps (open a
 * dialog, switch a tab, submit an empty form), and writes:
 *
 *   <outDir>/<shot>--<persona>--<lang>--<width>.png
 *   <outDir>/report.json   console errors, failed requests, horizontal
 *                          overflow and leaked i18n keys per screenshot
 *
 * Run from `frontend/` (it resolves Playwright from there):
 *
 *   node ../.claude/skills/ui-review/capture.mjs plan.json
 *
 * The plan is JSON:
 *
 *   {
 *     "outDir": "/tmp/ui-review-1032",          // required
 *     "baseUrl": "http://localhost:5173",       // default: the dev stack
 *     "apiUrl": "http://localhost:8001/api/v1",
 *     "zev": "ZEV STWEG Sonnenhof",             // pinned as preferred ZEV; null to skip
 *     "widths": [1440, 1024, 400],              // defaults for every shot
 *     "langs": ["de"],
 *     "shots": [
 *       { "name": "energy", "persona": "anna", "path": "/me/energy" },
 *       { "name": "energy-setup", "persona": "anna", "path": "/me/energy",
 *         "steps": [{ "click": "role=button[name=/Verbinden|Connect/]" }],
 *         "mode": "viewport", "langs": ["de", "fr"], "forcedColors": true }
 *     ]
 *   }
 *
 * Personas are the seed_demo accounts (admin, owner, manager, viewer, anna,
 * ben, clara, mixed, household, organisation, treuhand, former, newcomer);
 * any other name is taken as "<name>@openzev.local" with "<name>1234".
 *
 * Steps run in order before the shot: { "click": sel }, { "fill": sel, "value": v },
 * { "press": key }, { "hover": sel }, { "waitFor": sel }, { "wait": ms },
 * { "goto": path }. Selectors are Playwright selectors (css, text=, role=).
 * A failing step is recorded in the report and the shot is still taken, so a
 * broken interaction is visible rather than silently skipped.
 */
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'

const require = createRequire(path.join(process.cwd(), 'package.json'))
let chromium
try {
  ;({ chromium } = require('@playwright/test'))
} catch {
  console.error('Cannot resolve @playwright/test — run this from frontend/ after npm install.')
  process.exit(2)
}

const planPath = process.argv[2]
if (!planPath) {
  console.error('usage: node capture.mjs <plan.json>')
  process.exit(2)
}
const plan = JSON.parse(fs.readFileSync(planPath, 'utf8'))
const BASE = plan.baseUrl ?? 'http://localhost:5173'
const API = plan.apiUrl ?? 'http://localhost:8001/api/v1'
const OUT = path.resolve(plan.outDir ?? '')
if (!plan.outDir) {
  console.error('plan.outDir is required')
  process.exit(2)
}
const ZEV = plan.zev === undefined ? 'ZEV STWEG Sonnenhof' : plan.zev
fs.mkdirSync(OUT, { recursive: true })

const credentials = name => [`${name}@openzev.local`, `${name}1234`]

// A dotted lowercase token on screen is almost always a missing translation.
const I18N_KEY = /^[a-z][a-zA-Z0-9]*(\.[a-zA-Z0-9_]+){2,}$/

async function signIn(context, persona) {
  const [email, password] = credentials(persona)
  const resp = await context.request.post(`${API}/auth/token/`, { data: { email, password } })
  if (!resp.ok()) throw new Error(`sign-in as ${email} failed (${resp.status()}); is seed_demo loaded?`)
  if (!ZEV) return
  const cookies = await context.cookies(API)
  const token = cookies.find(c => c.name === 'openzev_access')?.value
  const headers = { Authorization: `Bearer ${token}` }
  const zevs = await context.request.get(`${API}/zev/zevs/`, { headers })
  if (!zevs.ok()) return // participants may not list communities; their shell picks one
  const id = (await zevs.json()).results?.find(z => z.name === ZEV)?.id
  if (id) await context.request.patch(`${API}/auth/me/`, { headers, data: { preferred_zev: id } })
}

async function settle(page) {
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.evaluate(() => document.fonts.ready)
  await page.locator('.skeleton-block:visible').first().waitFor({ state: 'detached', timeout: 20_000 }).catch(() => {})
  await page.mouse.move(0, 0)
  await page.waitForTimeout(300)
}

async function runStep(page, step) {
  if (step.goto) await page.goto(`${BASE}${step.goto}`)
  else if (step.click) await page.locator(step.click).first().click({ timeout: 10_000 })
  else if (step.fill) await page.locator(step.fill).first().fill(step.value ?? '')
  else if (step.press) await page.keyboard.press(step.press)
  else if (step.hover) await page.locator(step.hover).first().hover()
  else if (step.waitFor) await page.locator(step.waitFor).first().waitFor({ timeout: 10_000 })
  else if (step.wait) await page.waitForTimeout(step.wait)
  await settle(page)
}

async function inspect(page) {
  return page.evaluate(I18N_SOURCE => {
    const keyPattern = new RegExp(I18N_SOURCE)
    const doc = document.documentElement
    const overflowX = doc.scrollWidth - doc.clientWidth
    const wide = []
    if (overflowX > 1) {
      for (const el of document.querySelectorAll('main *')) {
        const r = el.getBoundingClientRect()
        if (r.right > doc.clientWidth + 1 && r.width > 0) {
          wide.push(`${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''}`)
          if (wide.length >= 8) break
        }
      }
    }
    const keys = new Set()
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    while (walker.nextNode()) {
      const text = walker.currentNode.textContent.trim()
      if (keyPattern.test(text)) keys.add(text)
    }
    return {
      overflowX,
      overflowing: wide,
      leakedI18nKeys: [...keys],
      title: document.title,
      h1: document.querySelector('h1')?.textContent?.trim() ?? null,
    }
  }, I18N_KEY.source)
}

async function screenshot(page, file, mode, width) {
  if (mode === 'viewport') {
    await page.screenshot({ path: file })
    return
  }
  // Grow the viewport to the content instead of fullPage, so sticky chrome and
  // 100dvh panes render as the user sees them.
  for (let i = 0; i < 3; i++) {
    const height = await page.evaluate(() => document.documentElement.scrollHeight)
    const current = page.viewportSize().height
    if (height <= current) break
    await page.setViewportSize({ width, height: Math.min(height, 12_000) })
    await page.waitForTimeout(300)
  }
  await page.screenshot({ path: file })
}

const browser = await chromium.launch()
const report = []
const contexts = new Map()

async function contextFor(persona, lang, forcedColors) {
  const key = `${persona}|${lang}|${forcedColors}`
  if (contexts.has(key)) return contexts.get(key)
  const context = await browser.newContext({
    locale: lang === 'de' ? 'de-CH' : lang,
    reducedMotion: 'reduce',
    forcedColors: forcedColors ? 'active' : 'none',
  })
  await context.addInitScript(language => {
    if (window.top !== window) return
    try {
      localStorage.setItem('openzev.language', language)
      localStorage.setItem('openzev.sidebarCollapsed', 'false')
    } catch {
      // Storage may be unavailable in a frame.
    }
  }, lang)
  await signIn(context, persona)
  contexts.set(key, context)
  return context
}

for (const shot of plan.shots ?? []) {
  const widths = shot.widths ?? plan.widths ?? [1440, 400]
  const langs = shot.langs ?? plan.langs ?? ['de']
  const persona = shot.persona ?? 'admin'
  for (const lang of langs) {
    for (const width of widths) {
      const name = `${shot.name}--${persona}--${lang}--${width}${shot.forcedColors ? '--forced' : ''}`
      const entry = { name, persona, lang, width, path: shot.path, consoleErrors: [], failedRequests: [], stepErrors: [] }
      let page
      try {
        const context = await contextFor(persona, lang, !!shot.forcedColors)
        page = await context.newPage()
        await page.setViewportSize({ width, height: shot.height ?? 900 })
        page.on('console', msg => { if (msg.type() === 'error') entry.consoleErrors.push(msg.text()) })
        page.on('pageerror', err => entry.consoleErrors.push(`pageerror: ${err.message}`))
        page.on('response', resp => {
          if (resp.status() >= 400 && resp.url().startsWith(API)) entry.failedRequests.push(`${resp.status()} ${resp.request().method()} ${resp.url().slice(API.length)}`)
        })
        await page.goto(`${BASE}${shot.path}`)
        await settle(page)
        for (const step of shot.steps ?? []) {
          try {
            await runStep(page, step)
          } catch (err) {
            entry.stepErrors.push(`${JSON.stringify(step)}: ${err.message.split('\n')[0]}`)
            break
          }
        }
        Object.assign(entry, await inspect(page))
        entry.url = page.url().slice(BASE.length)
        entry.file = path.join(OUT, `${name}.png`)
        await screenshot(page, entry.file, shot.mode ?? 'full', width)
      } catch (err) {
        entry.error = err.message.split('\n')[0]
      } finally {
        await page?.close().catch(() => {})
      }
      report.push(entry)
      const flags = [
        entry.error && `ERROR ${entry.error}`,
        entry.stepErrors.length && `${entry.stepErrors.length} step error(s)`,
        entry.consoleErrors.length && `${entry.consoleErrors.length} console error(s)`,
        entry.failedRequests.length && `${entry.failedRequests.length} failed request(s)`,
        entry.overflowX > 1 && `overflow-x ${entry.overflowX}px`,
        entry.leakedI18nKeys?.length && `i18n keys: ${entry.leakedI18nKeys.join(', ')}`,
      ].filter(Boolean)
      console.log(`${flags.length ? '!' : '✓'} ${name}${flags.length ? '  — ' + flags.join('; ') : ''}`)
    }
  }
}

fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2))
await browser.close()
console.log(`\n${report.length} screenshot(s) and report.json in ${OUT}`)
