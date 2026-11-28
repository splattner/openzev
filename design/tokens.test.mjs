import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import os from 'node:os'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')

describe('design tokens', () => {
  it('generator is idempotent (--check passes)', () => {
    const result = spawnSync('node', [path.join(ROOT, 'scripts', 'generate-tokens.mjs'), '--check'], {
      encoding: 'utf8',
    })
    assert.equal(result.status, 0, `generate-tokens --check failed:\n${result.stdout}\n${result.stderr}`)
  })

  it('brand-ramp luminance is strictly monotonic (inversions are rejected)', () => {
    // Negative test: copy the pipeline into a temp tree (the generator resolves
    // ROOT from its own location), reintroduce the historical --brand-glow ↔
    // --brand-muted inversion, and assert the gate fails in BOTH generate and
    // --check modes — the --check path is what CI (pr-quality.yml) runs.
    const tmp = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'tokens-monotonicity-'))
    try {
      fs.mkdirSync(path.join(tmp, 'scripts'), { recursive: true })
      fs.mkdirSync(path.join(tmp, 'design'), { recursive: true })
      fs.copyFileSync(path.join(ROOT, 'scripts', 'generate-tokens.mjs'), path.join(tmp, 'scripts', 'generate-tokens.mjs'))
      const tokens = JSON.parse(fs.readFileSync(path.join(ROOT, 'design', 'tokens.json'), 'utf8'))
      const swapped = JSON.parse(JSON.stringify(tokens))
      swapped.primitives['--brand-glow'] = tokens.primitives['--brand-muted']
      swapped.primitives['--brand-muted'] = tokens.primitives['--brand-glow']
      fs.writeFileSync(path.join(tmp, 'design', 'tokens.json'), JSON.stringify(swapped, null, 2))

      for (const mode of [[], ['--check']]) {
        const result = spawnSync('node', [path.join(tmp, 'scripts', 'generate-tokens.mjs'), ...mode], {
          encoding: 'utf8',
        })
        assert.notEqual(result.status, 0, `inverted ramp must fail generate mode ${JSON.stringify(mode)}`)
        assert.match(
          result.stderr,
          /Brand ramp inversion at steps 3→4: #[0-9a-f]{6} \(L=[0-9.]+\) must be lighter than #[0-9a-f]{6} \(L=[0-9.]+\)/,
          `gate must fail with an actionable inversion message in mode ${JSON.stringify(mode)}`
        )
      }

      // Strictness: adjacent steps with equal luminance (duplicate hex) must
      // also fail — monotonicity is strictly decreasing, not non-increasing.
      const tied = JSON.parse(JSON.stringify(tokens))
      tied.primitives['--brand-glow'] = tokens.primitives['--brand-light']
      fs.writeFileSync(path.join(tmp, 'design', 'tokens.json'), JSON.stringify(tied, null, 2))
      const tieResult = spawnSync('node', [path.join(tmp, 'scripts', 'generate-tokens.mjs'), '--check'], {
        encoding: 'utf8',
      })
      assert.notEqual(tieResult.status, 0, 'equal-luminance adjacent steps must fail (strictly decreasing, not non-increasing)')
      assert.match(tieResult.stderr, /Brand ramp inversion at steps 2→3/)
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true })
    }
  })

  it('generated files are present and non-empty', () => {
    const files = [
      'frontend/src/styles/tokens.css',
      'frontend/src/styles/generatedTheme.ts',
      'frontend/src/lib/chartTokens.ts',
      'backend/invoices/generated_chart_tokens.py',
      'backend/templates/pdf/_tokens.css',
    ]
    for (const rel of files) {
      const p = path.join(ROOT, rel)
      assert.ok(fs.existsSync(p), `Missing generated file: ${rel}`)
      const content = fs.readFileSync(p, 'utf8')
      assert.ok(content.length > 20, `${rel} is unexpectedly empty`)
      assert.ok(content.includes('Generated — do not edit'), `${rel} missing generated header`)
    }
  })

  it('primitives match shared PDF base include', () => {
    const pdfTokens = fs.readFileSync(path.join(ROOT, 'backend/templates/pdf/_tokens.css'), 'utf8')
    const tokensJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'design/tokens.json'), 'utf8'))
    for (const [k, v] of Object.entries(tokensJson.primitives)) {
      assert.ok(pdfTokens.includes(`${k}: ${v}`), `PDF tokens missing ${k}: ${v}`)
    }
  })

  it('field tokens are emitted to the frontend stylesheet only', () => {
    const css = fs.readFileSync(path.join(ROOT, 'frontend/src/styles/tokens.css'), 'utf8')
    const tokensJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'design/tokens.json'), 'utf8'))
    for (const [k, v] of Object.entries(tokensJson.fields)) {
      assert.ok(css.includes(`${k}: ${v}`), `tokens.css missing ${k}: ${v}`)
    }
    for (const rel of ['backend/invoices/generated_chart_tokens.py', 'backend/templates/pdf/_tokens.css', 'frontend/src/lib/chartTokens.ts']) {
      const content = fs.readFileSync(path.join(ROOT, rel), 'utf8')
      assert.ok(!content.includes('--field-'), `${rel} must stay color-only`)
    }
  })

  it('field, radius and shadow tokens reject malformed values', () => {
    // Copy the generator into a temp tree because it resolves paths relative to itself.
    const cases = [
      ['non-dimension value', 'fields', { '--field-height': 'huge' }, /Field --field-height must be a dimension literal/],
      ['hex value', 'fields', { '--field-height': '#ffffff' }, /Field --field-height must be a dimension literal/],
      ['wrong key prefix', 'fields', { '--height': '3.25rem' }, /Field key must start with --field-/],
      ['non-dimension radius', 'radius', { '--radius-md': 'round' }, /Radius --radius-md must be a dimension literal/],
      ['radius key with a space', 'radius', { '--radius-bad key': '4px' }, /Radius key must be --radius-<name>/],
      ['hex shadow', 'shadow', { '--shadow-sheet': '0 1px 2px #000000' }, /Shadow --shadow-sheet must be offsets \+ rgba/],
      ['shadow layer without rgba', 'shadow', { '--shadow-raised': '0 1px 2px rgba(0, 0, 0, 0.1), 0 6px 16px black' }, /Shadow --shadow-raised must be offsets \+ rgba/],
      ['unitless shadow offset', 'shadow', { '--shadow-sheet': '0 1 2px rgba(0, 0, 0, 0.1)' }, /Shadow --shadow-sheet must be offsets \+ rgba/],
      ['negative shadow blur', 'shadow', { '--shadow-sheet': '0 1px -2px rgba(0, 0, 0, 0.1)' }, /Shadow --shadow-sheet must be offsets \+ rgba/],
      ['incomplete rgba()', 'shadow', { '--shadow-sheet': '0 1px 2px rgba(15)' }, /Shadow --shadow-sheet must be offsets \+ rgba/],
    ]
    for (const [label, group, override, message] of cases) {
      const tmp = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'tokens-validation-'))
      try {
        fs.mkdirSync(path.join(tmp, 'scripts'), { recursive: true })
        fs.mkdirSync(path.join(tmp, 'design'), { recursive: true })
        fs.copyFileSync(path.join(ROOT, 'scripts', 'generate-tokens.mjs'), path.join(tmp, 'scripts', 'generate-tokens.mjs'))
        const tokens = JSON.parse(fs.readFileSync(path.join(ROOT, 'design/tokens.json'), 'utf8'))
        Object.assign(tokens[group], override)
        fs.writeFileSync(path.join(tmp, 'design', 'tokens.json'), JSON.stringify(tokens))
        const result = spawnSync('node', [path.join(tmp, 'scripts', 'generate-tokens.mjs'), '--check'], {
          encoding: 'utf8',
        })
        assert.notEqual(result.status, 0, `${label} must fail validation`)
        assert.match(result.stderr, message, `${label} must fail with the group's validation message`)
      } finally {
        fs.rmSync(tmp, { recursive: true, force: true })
      }
    }
  })

  it('chart tokens are resolved literals (no var(--))', () => {
    const ts = fs.readFileSync(path.join(ROOT, 'frontend/src/lib/chartTokens.ts'), 'utf8')
    const py = fs.readFileSync(path.join(ROOT, 'backend/invoices/generated_chart_tokens.py'), 'utf8')
    assert.ok(!ts.includes('var(--'), 'chartTokens.ts must contain resolved hex literals, not var(--)')
    assert.ok(!py.includes('var(--'), 'generated_chart_tokens.py must contain resolved hex literals')
    assert.ok(ts.includes('CHART_LOCAL'), 'chartTokens.ts missing CHART_LOCAL')
    assert.ok(py.includes('_CHART_LOCAL'), 'generated_chart_tokens.py missing _CHART_LOCAL')
    assert.ok(ts.includes('DIVERGING_POSITIVE'), 'chartTokens.ts missing DIVERGING_POSITIVE')
    assert.ok(py.includes('_DIVERGING_POSITIVE'), 'generated_chart_tokens.py missing _DIVERGING_POSITIVE')
  })

  it('emits radius and shadow tokens only to tokens.css', () => {
    const css = fs.readFileSync(path.join(ROOT, 'frontend/src/styles/tokens.css'), 'utf8')
    const tokensJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'design/tokens.json'), 'utf8'))
    for (const group of ['radius', 'shadow']) {
      for (const [k, v] of Object.entries(tokensJson[group])) {
        assert.ok(css.includes(`${k}: ${v}`), `tokens.css missing ${k}: ${v}`)
      }
    }
    const scaleKeys = /--(radius|shadow)-/
    for (const rel of ['backend/invoices/generated_chart_tokens.py', 'backend/templates/pdf/_tokens.css', 'frontend/src/lib/chartTokens.ts']) {
      const content = fs.readFileSync(path.join(ROOT, rel), 'utf8')
      assert.ok(!scaleKeys.test(content), `${rel} must not contain radius or shadow tokens`)
    }
    const base = fs.readFileSync(path.join(ROOT, 'frontend/src/styles/base.css'), 'utf8')
    assert.ok(!/--(radius|shadow)-[a-z0-9-]+\s*:/.test(base), 'base.css must not define radius/shadow tokens')
  })

  it('every radius and shadow token the frontend uses is defined', () => {
    const tokensJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'design/tokens.json'), 'utf8'))
    const defined = new Set([...Object.keys(tokensJson.radius), ...Object.keys(tokensJson.shadow)])
    const src = path.join(ROOT, 'frontend/src')
    const missing = []
    for (const rel of fs.readdirSync(src, { recursive: true })) {
      if (!/\.(css|tsx?)$/.test(rel)) continue
      for (const m of fs.readFileSync(path.join(src, rel), 'utf8').matchAll(/var\((--(?:radius|shadow)-[a-z0-9-]+)/g)) {
        if (!defined.has(m[1])) missing.push(`${rel}: ${m[1]}`)
      }
    }
    assert.deepEqual(missing, [], 'undefined radius/shadow tokens resolve to nothing')
  })
})
