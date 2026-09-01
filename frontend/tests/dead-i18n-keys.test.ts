import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { en } from '../src/i18n/locales/en'

/**
 * No dead i18n keys: every key defined in the locale files must be reachable
 * from code. Dead keys accumulate silently after redesigns (the invoice
 * detail and management-page rewrites left whole `col.*` families behind)
 * and every locale must carry them forever — locale parity makes a dead key
 * a 4× maintenance tax.
 *
 * Liveness rules, in order:
 * 1. exact key string in the corpus (src + tests + screenshots, minus locales)
 * 2. i18next plural fallback: strip _one/_other/…, retry exact
 * 3. dynamic: the key extends the literal head of a real dynamic call site
 *    — t(`prefix.${expr}`) — directly or via a variable assigned a template
 *    literal that is later passed to t().
 *
 * Prefixes are full literal heads only (never shorter ancestors): rescuing
 * `auth.` from `auth.oauth.errors.${code}` would keep the whole auth tree
 * alive. When this test fails, delete the listed keys from ALL FOUR locales
 * (or, if a key is actually used, make the call site static so rule 1
 * catches regressions).
 */

const ROOT = resolve(__dirname, '..')
const SRC = join(ROOT, 'src')

function sourceFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const p = join(dir, entry.name)
        if (entry.isDirectory()) return sourceFiles(p)
        // skip locale data and this test's own doc comments
        return /\.(tsx?|ts)$/.test(entry.name) && !p.includes('i18n/locales') && !p.endsWith('dead-i18n-keys.test.ts') ? [p] : []
    })
}

const corpus = [
    ...sourceFiles(SRC),
    ...sourceFiles(join(ROOT, 'tests')),
    ...sourceFiles(join(ROOT, 'screenshots')),
]
    .map((f) => readFileSync(f, 'utf8'))
    .join('\n')

function flatten(obj: Record<string, unknown>, prefix = ''): string[] {
    return Object.entries(obj).flatMap(([k, v]) => {
        const kp = prefix ? `${prefix}.${k}` : k
        return v && typeof v === 'object' ? flatten(v as Record<string, unknown>, kp) : [kp]
    })
}

function localeKeys(): string[] {
    return flatten(en as Record<string, unknown>)
}

const dynamicPrefixes: Record<string, true> = {}
function addPrefixes(literalHead: string): void {
    const p = literalHead.endsWith('.') ? literalHead : `${literalHead}.`
    dynamicPrefixes[p] = true
}
// direct: t(`prefix.${expr}`) — tolerate TS casts and t options after the
// template. Word-boundary before t( so test(/post( in e2e specs don't feed
// URL paths in as prefixes; heads must be key-shaped (lowercase dot path).
const KEY_HEAD = /^[a-z][a-zA-Z0-9]*(\.[a-zA-Z0-9_]+)*\.?$/
for (const m of corpus.matchAll(/(^|[^a-zA-Z0-9_])t\(`([^`]*?)\$\{[^}]*\}[^`]*`[^)]*\)/g)) {
    if (KEY_HEAD.test(m[2])) addPrefixes(m[2])
}
// indirect: ... = `prefix.${expr}` (variable later passed to t)
for (const m of corpus.matchAll(/[=:]\s*`([a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9_]+)*)\.\$\{[^}]*\}[^`]*`/g)) addPrefixes(m[1])

function used(k: string): boolean {
    const escaped = k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return new RegExp(`(^|[^a-zA-Z0-9_.])${escaped}([^a-zA-Z0-9_]|$)`).test(corpus)
}

function isLive(key: string): boolean {
    if (used(key)) return true
    const base = key.replace(/_(one|other|zero|two|few|many)$/, '')
    if (base !== key && used(base)) return true
    for (const p of Object.keys(dynamicPrefixes)) if (key.startsWith(p)) return true
    return false
}

describe('i18n locale keys', () => {
    it('are all reachable from code (no dead keys)', () => {
        const dead = localeKeys().filter((k) => !isLive(k))
        expect(dead).toEqual([])
    })

    it('flags a planted unreachable key as dead (negative path)', () => {
        expect(corpus).not.toContain('__probe__')
        const [probe] = flatten({ __probe__: { plantedKey: 'x' } })
        expect(probe).toBe('__probe__.plantedKey')
        expect(isLive(probe)).toBe(false)
    })
})
