#!/usr/bin/env node
// Color sweep — enforces "no raw color literals outside design/tokens.json and
// its generated outputs" (SPEC-2026-08-ui-redesign-pdf-style).
//
// Two violation classes:
//   1. Hex literals        — never allowed outside the exempt generated files.
//   2. rgb()/rgba()/hsl()/hsla() function literals — same rule; these bypassed
//      the original hex-only sweep (a legacy sky-blue rgba survived in the
//      template editor because of that blind spot).
//
// Alpha scrims/shadows (white/black/slate fades) are the one sanctioned use of
// raw color functions: allowlist them per file with a "@alpha" suffix in
// scripts/hex-migration-allowlist.json. An "@alpha" file may still use
// rgba()/hsla() but NOT hex or opaque rgb()/hsl() — new hues must go through
// tokens. Entries without the suffix exempt the file from both classes.
//
// Frontend: CSS/TS/TSX failures except the generated token outputs (stylelint
// covers CSS hex too; the script keeps one enforcement path for local runs).
// Backend: PDF/HTML templates and invoices Python failures except the
// generated _tokens.css / generated_chart_tokens.py; tests are exempt —
// test_pdf.py asserts rendered SVG values that legitimately repeat the
// generated palette.

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const ALLOWLIST_PATH = path.join(__dirname, 'hex-migration-allowlist.json')

// Exclude all-digit #-sequences of 3-5 chars (issue refs like #449).
// Real hex values in this project always contain at least one letter a-f.
const HEX_RE = /#(?!(?:\d{3,5}\b))(?:[0-9a-fA-F]{3,8})\b/
const COLOR_FN_RE = /\b(?:rgba?|hsla?)\(/i
const OPAQUE_COLOR_FN_RE = /\b(?:rgb|hsl)\(/i

// [root dir, file extension filter, generated/exempt files relative to root]
const TREES = [
  {
    dir: path.join(ROOT, 'frontend', 'src'),
    exts: /\.(css|ts|tsx)$/,
    exempt: new Set(['styles/tokens.css', 'styles/generatedTheme.ts', 'lib/chartTokens.ts']),
  },
  {
    dir: path.join(ROOT, 'backend', 'templates'),
    exts: /\.(html|css)$/,
    exempt: new Set(['pdf/_tokens.css']),
  },
  {
    dir: path.join(ROOT, 'backend', 'invoices'),
    exts: /\.py$/,
    exempt: new Set(['generated_chart_tokens.py']),
    nameFilter: (name) => !name.startsWith('test_'),
    // migrations may contain issue references like #401 in docstrings
    dirFilter: (name) => name !== 'migrations',
  },
]

let allowlist = []
try {
  allowlist = JSON.parse(fs.readFileSync(ALLOWLIST_PATH, 'utf8'))
} catch {
  allowlist = []
}
const fullyAllowed = new Set(allowlist.filter((entry) => !entry.endsWith('@alpha')))
const alphaAllowed = new Set(
  allowlist.filter((entry) => entry.endsWith('@alpha')).map((entry) => entry.slice(0, -'@alpha'.length)),
)

function* walk(dir, dirFilter) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (dirFilter && !dirFilter(entry.name)) continue
      yield* walk(path.join(dir, entry.name), dirFilter)
    } else {
      yield path.join(dir, entry.name)
    }
  }
}

const violations = []
for (const tree of TREES) {
  for (const file of walk(tree.dir, tree.dirFilter)) {
    const rel = path.relative(tree.dir, file).split(path.sep).join('/')
    if (!tree.exts.test(file)) continue
    if (tree.nameFilter && !tree.nameFilter(path.basename(file))) continue
    if (tree.exempt.has(rel) || fullyAllowed.has(rel)) continue
    const alphaOk = alphaAllowed.has(rel)
    const lines = fs.readFileSync(file, 'utf8').split('\n')
    lines.forEach((line, i) => {
      if (HEX_RE.test(line)) {
        violations.push(`${rel}:${i + 1}: ${line.trim().slice(0, 100)}`)
        return
      }
      if (COLOR_FN_RE.test(line) && !(alphaOk && !OPAQUE_COLOR_FN_RE.test(line))) {
        violations.push(`${rel}:${i + 1}: ${line.trim().slice(0, 100)}`)
      }
    })
  }
}

if (violations.length) {
  console.error(`Raw color literals found outside design/tokens.json and its generated outputs:`)
  console.error(violations.join('\n'))
  console.error(`\nFix: use var(--…) / generated chart constants. Alpha scrims/shadows may be allowlisted per file with a "@alpha" suffix in scripts/hex-migration-allowlist.json; opaque rgb()/hsl() and hex are never allowlistable.`)
  process.exit(1)
}
console.log('Color sweep passed — no raw color literals outside generated token outputs.')
