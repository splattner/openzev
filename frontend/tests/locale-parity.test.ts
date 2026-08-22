import { describe, expect, it } from 'vitest'
import { de } from '../src/i18n/locales/de'
import { en } from '../src/i18n/locales/en'
import { fr } from '../src/i18n/locales/fr'
import { it as itLocale } from '../src/i18n/locales/it'

function getLeafPaths(
  obj: Record<string, unknown>,
  prefix = '',
): { path: string; value: unknown }[] {
  return Object.entries(obj).flatMap(([key, val]) => {
    const fullPath = prefix ? `${prefix}.${key}` : key
    if (val !== null && typeof val === 'object' && !Array.isArray(val)) {
      return getLeafPaths(val as Record<string, unknown>, fullPath)
    }
    return [{ path: fullPath, value: val }]
  })
}

// Extract {{placeholder}} names from a string value.
// Matches bare {{name}}, space-padded {{ name }}, and formatted {{name, number}} / {{val, datetime}}.
function placeholders(val: string): string[] {
  const matches = val.matchAll(/\{\{\s*(\w+)[^}]*\}\}/g)
  return [...matches].map((m) => m[1]).sort()
}

describe('locale parity and integrity', () => {
  const enLeaves = getLeafPaths(en)
  const enMap = new Map(enLeaves.map((l) => [l.path, l.value]))

  it.each([
    ['de', de],
    ['fr', fr],
    ['it', itLocale],
  ])('%s matches en key structure exactly', (_name, locale) => {
    const localeKeys = getLeafPaths(locale)
      .map((l) => l.path)
      .sort()
    expect(localeKeys).toEqual([...enMap.keys()].sort())
  })

  it('every leaf is a non-empty string', () => {
    const allLocales = { en, de, fr, it: itLocale }
    for (const [name, dict] of Object.entries(allLocales)) {
      const bad = getLeafPaths(dict)
        .filter(
          (entry) =>
            typeof entry.value !== 'string' ||
            (entry.value as string).trim() === '',
        )
        .map((entry) => entry.path)
      expect(bad, `${name} has non-string or empty leaf values`).toEqual([])
    }
  })

  it('interpolation placeholders match across all locales', () => {
    const otherLocales = { de, fr, it: itLocale }
    for (const [name, dict] of Object.entries(otherLocales)) {
      const leaves = getLeafPaths(dict)
        .filter((e) => typeof e.value === 'string')
      for (const { path, value } of leaves) {
        const enValue = enMap.get(path)
        if (typeof enValue !== 'string') continue
        const enPh = placeholders(enValue)
        const otherPh = placeholders(value as string)
        expect(
          otherPh,
          `${name}.${path}: placeholder mismatch (en has ${enPh.join(',')}, got ${otherPh.join(',')})`,
        ).toEqual(enPh)
      }
    }
  })
})
