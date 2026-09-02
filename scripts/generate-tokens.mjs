#!/usr/bin/env node
// Generated-token pipeline — no dependencies.
// Reads design/tokens.json and emits five committed outputs.
// Usage: node scripts/generate-tokens.mjs [--check]

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const TOKENS_PATH = path.join(ROOT, 'design', 'tokens.json')

const OUTPUTS = {
  tokensCss: path.join(ROOT, 'frontend', 'src', 'styles', 'tokens.css'),
  generatedTheme: path.join(ROOT, 'frontend', 'src', 'styles', 'generatedTheme.ts'),
  chartTokens: path.join(ROOT, 'frontend', 'src', 'lib', 'chartTokens.ts'),
  pyTokens: path.join(ROOT, 'backend', 'invoices', 'generated_chart_tokens.py'),
  pdfTokens: path.join(ROOT, 'backend', 'templates', 'pdf', '_tokens.css'),
}

const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/
// Contains-check for "no raw hex anywhere in this value" — deliberately NOT
// g-flagged: a global regex is stateful across .test() calls (lastIndex),
// which makes results order-dependent.
const HEX_CONTAINS = /#[0-9a-fA-F]{3,8}\b/
const VAR_RE = /^var\(--[a-z0-9-]+\)$/

function loadTokens() {
  const raw = fs.readFileSync(TOKENS_PATH, 'utf8')
  return JSON.parse(raw)
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}

function relativeLuminance(hex) {
  // WCAG 2.1 relative luminance from sRGB hex (6-digit).
  const r = parseInt(hex.slice(1, 3), 16) / 255
  const g = parseInt(hex.slice(3, 5), 16) / 255
  const b = parseInt(hex.slice(5, 7), 16) / 255
  const lin = (c) => c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

function validate(tokens) {
  const required = ['primitives', 'semantics', 'themes', 'charts', 'type']
  for (const k of required) {
    assert(tokens[k] !== undefined, `Missing top-level key: ${k}`)
    assert(tokens[k] !== null && typeof tokens[k] === 'object' && !Array.isArray(tokens[k]), `Top-level key ${k} must be an object`)
  }

  // primitives: keys --*, values hex
  for (const [k, v] of Object.entries(tokens.primitives)) {
    assert(k.startsWith('--'), `Primitive key must start with --: ${k}`)
    assert(typeof v === 'string' && HEX_RE.test(v), `Primitive ${k} must be hex literal, got: ${v}`)
  }

  // semantics: keys --*, values var(--primitive) referencing existing primitive
  for (const [k, v] of Object.entries(tokens.semantics)) {
    assert(k.startsWith('--'), `Semantic key must start with --: ${k}`)
    assert(typeof v === 'string' && VAR_RE.test(v), `Semantic ${k} must be var(--…), got: ${v}`)
    const ref = v.slice(4, -1)
    assert(tokens.primitives[ref] !== undefined, `Semantic ${k} references unknown primitive ${ref}`)
    assert(!HEX_CONTAINS.test(v), `Semantic ${k} must not contain raw hex`)
  }

  // themes: each theme is map semantic -> var(--primitive)
  for (const [themeName, themeMap] of Object.entries(tokens.themes)) {
    assert(themeMap && typeof themeMap === 'object' && !Array.isArray(themeMap), `Theme ${themeName} must be an object`)
    for (const [k, v] of Object.entries(themeMap)) {
      assert(tokens.semantics[k] !== undefined, `Theme ${themeName} key ${k} not in semantics`)
      assert(typeof v === 'string' && VAR_RE.test(v), `Theme ${themeName} ${k} must be var(--…), got: ${v}`)
      const ref = v.slice(4, -1)
      assert(tokens.primitives[ref] !== undefined, `Theme ${themeName} ${k} references unknown primitive ${ref}`)
    }
  }

  // brand ramp inputs used by the Mantine theme generator
  for (const k of ['--brand-pale', '--brand-light', '--brand-muted', '--brand-glow', '--brand-accent', '--brand-step-5', '--brand-mid', '--brand', '--brand-deep', '--brand-ink']) {
    assert(tokens.primitives[k] !== undefined, `Missing primitive required by the brand ramp: ${k}`)
  }

  // charts: required keys, hex literals or arrays of hex
  const requiredCharts = ['local', 'grid', 'ink', 'muted', 'gridline', 'axis', 'bg', 'label', 'flowLocalCons', 'flowGridExp', 'prodColors', 'consColors', 'othersColor', 'axisColor', 'annotationColor', 'positiveColor', 'negativeColor', 'divergingPositive']
  for (const k of requiredCharts) {
    assert(tokens.charts[k] !== undefined, `Missing charts key: ${k}`)
  }
  for (const [k, v] of Object.entries(tokens.charts)) {
    if (Array.isArray(v)) {
      for (const item of v) {
        assert(typeof item === 'string' && HEX_RE.test(item), `charts.${k} array item must be hex, got: ${item}`)
      }
    } else {
      assert(typeof v === 'string' && HEX_RE.test(v), `charts.${k} must be hex literal, got: ${v}`)
    }
  }
  // Series arrays feed fixed positions (PDF series parity);
  // a short array would fail later, outside validation.
  assert(Array.isArray(tokens.charts.prodColors) && tokens.charts.prodColors.length >= 6,
    'charts.prodColors must have at least 6 entries (PDF series parity)')
  assert(Array.isArray(tokens.charts.consColors) && tokens.charts.consColors.length >= 6,
    'charts.consColors must have at least 6 entries (PDF series parity)')

  // type: must be object, must not contain hex
  assert(tokens.type && typeof tokens.type === 'object', 'type must be an object')
  const typeJson = JSON.stringify(tokens.type)
  assert(!HEX_CONTAINS.test(typeJson), 'type must not contain raw hex literals')

  // ensure no hex outside primitives and charts
  const semanticsJson = JSON.stringify(tokens.semantics)
  assert(!HEX_CONTAINS.test(semanticsJson), 'semantics must not contain raw hex (use var(--…) aliases)')
  for (const [name, cmap] of Object.entries(tokens.themes)) {
    const j = JSON.stringify(cmap)
    assert(!HEX_CONTAINS.test(j), `theme ${name} must not contain raw hex`)
  }
}

function generateTokensCss(tokens) {
  const lines = []
  lines.push('/* Generated — do not edit. Source: design/tokens.json */')
  lines.push(':root {')
  // primitives — sorted for determinism
  const primKeys = Object.keys(tokens.primitives).sort()
  for (const k of primKeys) {
    lines.push(`  ${k}: ${tokens.primitives[k]};`)
  }
  // semantics — sorted
  const semKeys = Object.keys(tokens.semantics).sort()
  for (const k of semKeys) {
    lines.push(`  ${k}: ${tokens.semantics[k]};`)
  }
  lines.push('}')
  // themes: emit [data-theme] overrides for any alternate theme maps
  // (the default theme is expressed by semantics in :root).
  const themeNames = Object.keys(tokens.themes).sort()
  for (const tName of themeNames) {
    lines.push(`[data-theme="${tName}"] {`)
    const tMap = tokens.themes[tName]
    for (const k of Object.keys(tMap).sort()) {
      lines.push(`  ${k}: ${tMap[k]};`)
    }
    lines.push('}')
  }
  lines.push('')
  return lines.join('\n')
}

function generatePdfTokensCss(tokens) {
  const lines = []
  lines.push('/* Generated — do not edit. Source: design/tokens.json */')
  lines.push(':root {')
  const primKeys = Object.keys(tokens.primitives).sort()
  for (const k of primKeys) {
    lines.push(`  ${k}: ${tokens.primitives[k]};`)
  }
  lines.push('}')
  lines.push('')
  return lines.join('\n')
}

function generateMantineTheme(tokens) {
  // Build a 10-step brand ramp. Mantine expects colors.brand[0..9], primaryShade 6.
  // Derived purely from tokens — no hex literals may live in this file.
  const p = tokens.primitives
  const ramp = [
    p['--brand-pale'],                 // 0 lightest
    p['--brand-light'],                // 1
    p['--brand-glow'],                 // 2
    p['--brand-muted'],                // 3
    p['--brand-accent'],               // 4
    p['--brand-step-5'],               // 5 mid-light (named primitive, not charts.prodColors[1])
    p['--brand-mid'],                  // 6 primaryShade = interactive
    p['--brand'],                      // 7
    p['--brand-deep'],                 // 8
    p['--brand-ink'],                  // 9 darkest
  ]
  for (const v of ramp) assert(HEX_RE.test(v), `Brand ramp entry must be hex, got: ${v}`)

  // Luminance monotonicity: the ramp goes pale (bright) → ink (dark),
  // so each step must be strictly lower luminance than the previous.
  for (let i = 1; i < ramp.length; i++) {
    const lumPrev = relativeLuminance(ramp[i - 1])
    const lumCurr = relativeLuminance(ramp[i])
    assert(
      lumCurr < lumPrev,
      `Brand ramp inversion at steps ${i}→${i + 1}: ${ramp[i - 1]} (L=${lumPrev.toFixed(4)}) must be lighter than ${ramp[i]} (L=${lumCurr.toFixed(4)})`
    )
  }

  const fontFamily = tokens.type?.fontFamily?.screen || "'Inter Variable', Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
  const lines = []
  lines.push('// Generated — do not edit. Source: design/tokens.json')
  lines.push("import { createTheme } from '@mantine/core'")
  lines.push('')
  lines.push('export const generatedTheme = createTheme({')
  lines.push(`  fontFamily: ${JSON.stringify(fontFamily)},`)
  lines.push(`  primaryColor: 'brand',`)
  lines.push(`  primaryShade: 6,`)
  lines.push(`  colors: {`)
  lines.push(`    brand: [`)
  for (let i = 0; i < ramp.length; i++) {
    const comma = i < ramp.length - 1 ? ',' : ''
    lines.push(`      ${JSON.stringify(ramp[i])}${comma}`)
  }
  lines.push(`    ],`)
  lines.push(`  },`)
  lines.push('})')
  lines.push('')
  return lines.join('\n')
}

function generateChartTokensTs(tokens) {
  const c = tokens.charts
  const lines = []
  lines.push('// Generated — do not edit. Source: design/tokens.json')
  lines.push('// Chart palette — resolved literals for Recharts / SVG (CSS variables do not resolve in fill="…" props).')
  lines.push('')
  const map = {
    CHART_LOCAL: c.local,
    CHART_GRID: c.grid,
    CHART_INK: c.ink,
    CHART_MUTED: c.muted,
    CHART_GRIDLINE: c.gridline,
    CHART_AXIS: c.axis,
    CHART_LABEL: c.label,
    FLOW_LOCAL_CONS: c.flowLocalCons,
    FLOW_GRID_EXP: c.flowGridExp,
    OTHERS_COLOR: c.othersColor,
    AXIS_COLOR: c.axisColor,
    ANNOTATION_COLOR: c.annotationColor,
    POSITIVE_COLOR: c.positiveColor,
    NEGATIVE_COLOR: c.negativeColor,
    DIVERGING_POSITIVE: c.divergingPositive,
  }
  for (const [k, v] of Object.entries(map)) {
    lines.push(`export const ${k} = ${JSON.stringify(v)}`)
  }
  lines.push(`export const PROD_COLORS: readonly string[] = ${JSON.stringify(c.prodColors)}`)
  lines.push(`export const CONS_COLORS: readonly string[] = ${JSON.stringify(c.consColors)}`)
  lines.push('')
  return lines.join('\n')
}

function generatePyTokens(tokens) {
  const c = tokens.charts
  const lines = []
  lines.push('# Generated — do not edit. Source: design/tokens.json')
  lines.push('"""Chart palette mirrors design/tokens.json:charts — resolved literals for PDF SVG."""')
  lines.push('')
  lines.push(`_CHART_LOCAL = ${JSON.stringify(c.local)}`)
  lines.push(`_CHART_GRID = ${JSON.stringify(c.grid)}`)
  lines.push(`_CHART_INK = ${JSON.stringify(c.ink)}`)
  lines.push(`_CHART_MUTED = ${JSON.stringify(c.muted)}`)
  lines.push(`_CHART_GRIDLINE = ${JSON.stringify(c.gridline)}`)
  lines.push(`_CHART_AXIS = ${JSON.stringify(c.axis)}`)
  // _CHART_BG is Python-only: screen charts use CSS custom property
  // var(--chart-surface) and never need a resolved literal for the bg color.
  // labelOnFill is Python-only: no screen chart currently paints on-bar labels.
  lines.push(`_CHART_BG = ${JSON.stringify(c.bg)}`)
  lines.push(`_CHART_LABEL = ${JSON.stringify(c.label)}`)
  lines.push(`_FLOW_LOCAL_CONS = ${JSON.stringify(c.flowLocalCons)}`)
  lines.push(`_FLOW_GRID_EXP = ${JSON.stringify(c.flowGridExp)}`)
  lines.push(`PROD_COLORS = ${JSON.stringify(c.prodColors)}`)
  lines.push(`CONS_COLORS = ${JSON.stringify(c.consColors)}`)
  lines.push(`_OTHERS_COLOR = ${JSON.stringify(c.othersColor)}`)
  lines.push(`POSITIVE_COLOR = ${JSON.stringify(c.positiveColor)}`)
  lines.push(`NEGATIVE_COLOR = ${JSON.stringify(c.negativeColor)}`)
  lines.push(`_DIVERGING_POSITIVE = ${JSON.stringify(c.divergingPositive)}`)
  // On-bar label fill — Python-only: no screen chart currently paints on-bar labels.
  if (c.labelOnFill) lines.push(`_CHART_LABEL_ON_FILL = ${JSON.stringify(c.labelOnFill)}`)
  lines.push('')
  return lines.join('\n')
}

function ensureDir(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
}

function writeOutput(filePath, content) {
  ensureDir(filePath)
  fs.writeFileSync(filePath, content, 'utf8')
}

function main() {
  const args = process.argv.slice(2)
  const check = args.includes('--check') || args.includes('--verify')

  let tokens
  let outputs
  try {
    tokens = loadTokens()
    validate(tokens)
    outputs = {
      [OUTPUTS.tokensCss]: generateTokensCss(tokens),
      [OUTPUTS.generatedTheme]: generateMantineTheme(tokens),
      [OUTPUTS.chartTokens]: generateChartTokensTs(tokens),
      [OUTPUTS.pyTokens]: generatePyTokens(tokens),
      [OUTPUTS.pdfTokens]: generatePdfTokensCss(tokens),
    }
  } catch (e) {
    console.error(`Token pipeline failed: ${e.message}`)
    process.exit(1)
  }

  if (check) {
    let hasDrift = false
    for (const [filePath, expected] of Object.entries(outputs)) {
      let actual = null
      try {
        actual = fs.readFileSync(filePath, 'utf8')
      } catch {
        console.error(`Missing generated file: ${path.relative(ROOT, filePath)}`)
        hasDrift = true
        continue
      }
      if (actual !== expected) {
        console.error(`Drift in ${path.relative(ROOT, filePath)} — run: node scripts/generate-tokens.mjs`)
        hasDrift = true
      }
    }
    if (hasDrift) process.exit(1)
    console.log('Tokens check passed — all generated files up to date.')
    return
  }

  for (const [filePath, content] of Object.entries(outputs)) {
    writeOutput(filePath, content)
    console.log(`Wrote ${path.relative(ROOT, filePath)}`)
  }
}

main()
