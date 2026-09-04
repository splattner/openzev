#!/usr/bin/env node
// Build the GitHub release body for a version: the hand-written notes from
// docs/release-notes/<version>.md, then "## Full change list", then
// release-please's generated body.
//
// Two things here are easy to get wrong by hand and are the reason this is a
// script rather than a step in the skill's prose:
//
//   1. The state block. `<!-- release-notes-state ... -->` is bookkeeping for
//      the `continue` mode and must never reach the published release.
//
//   2. Image paths. A release body has no file context, so GitHub resolves a
//      relative path against the *repository root* at the release's tag —
//      while the same markdown file in the repo resolves it against
//      docs/release-notes/. The two cannot both be satisfied by one path, and
//      a `../` path is resolved wrongly in a release body (the `..` eats the
//      tag ref). So the draft keeps repo-correct relative paths for review,
//      and this rewrites them to absolute raw URLs pinned to the tag, which
//      render identically everywhere and survive the body being copied
//      elsewhere.
//
// Usage:
//   node scripts/release-notes-body.mjs <version> --generated <file> [--repo owner/name]
//
// Writes the combined body to stdout.

import fs from 'fs'
import path from 'path'

const args = process.argv.slice(2)
const version = args[0]
const flag = (name, fallback) => {
  const i = args.indexOf(`--${name}`)
  return i === -1 ? fallback : args[i + 1]
}

if (!version || version.startsWith('--')) {
  console.error('usage: release-notes-body.mjs <version> --generated <file> [--repo owner/name]')
  process.exit(2)
}

const repo = flag('repo', 'splattner/openzev')
const generatedPath = flag('generated')
const tag = `v${version}`
const notesDir = path.join('docs', 'release-notes')
const notesPath = path.join(notesDir, `${version}.md`)

if (!fs.existsSync(notesPath)) {
  console.error(`No draft at ${notesPath}. Run the release-notes skill in draft mode first.`)
  process.exit(1)
}
if (!generatedPath || !fs.existsSync(generatedPath)) {
  console.error('--generated must point at a file holding release-please\'s generated body.')
  process.exit(1)
}

let notes = fs.readFileSync(notesPath, 'utf8')

// 1. Drop the bookkeeping block.
notes = notes.replace(/\n*<!--\s*release-notes-state[\s\S]*?-->\s*$/, '\n')

// 2. Pin relative image paths to the tag. Absolute URLs are left alone.
const missing = []
notes = notes.replace(/!\[([^\]]*)\]\(([^)\s]+)(\s+"[^"]*")?\)/g, (match, alt, target, title) => {
  if (/^(https?:)?\/\//.test(target) || target.startsWith('data:')) return match
  const repoRelative = path.posix.normalize(path.posix.join(notesDir, target))
  if (!fs.existsSync(repoRelative)) missing.push(`${target} (resolved to ${repoRelative})`)
  return `![${alt}](https://raw.githubusercontent.com/${repo}/${tag}/${repoRelative}${title ?? ''})`
})

// An image that 404s in a release nobody can edit afterwards is worse than a
// note with no image, so refuse rather than publish a broken one.
if (missing.length) {
  console.error(`Referenced image(s) not found under ${notesDir}:`)
  for (const m of missing) console.error(`  - ${m}`)
  process.exit(1)
}

const generated = fs.readFileSync(generatedPath, 'utf8').trim()
process.stdout.write(`${notes.trimEnd()}\n\n## Full change list\n\n${generated}\n`)
