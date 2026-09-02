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
})
