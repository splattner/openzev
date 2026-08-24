import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
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
