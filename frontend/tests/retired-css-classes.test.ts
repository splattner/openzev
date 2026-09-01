import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

/**
 * Class names retired by the UI redesign. They have no rule in any stylesheet,
 * so markup still carrying them silently gets no styling at all — the failure
 * mode is a page that looks *almost* right, which is why they survived several
 * cleanup passes (#486, then #491).
 *
 * Not a general "every class has a rule" check: `.button-primary` alone is on
 * 52 call sites and is a deliberate readability marker rather than an
 * oversight, since `.button` already carries the primary appearance.
 */
const RETIRED_CLASSES = ['form-group', 'button-sm']

const SRC = resolve(__dirname, '../src')

function sourceFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name)
        if (entry.isDirectory()) return sourceFiles(path)
        return /\.tsx?$/.test(entry.name) ? [path] : []
    })
}

describe('retired CSS classes', () => {
    it('are gone from the source tree', () => {
        const offenders: string[] = []
        for (const file of sourceFiles(SRC)) {
            const contents = readFileSync(file, 'utf8')
            for (const className of RETIRED_CLASSES) {
                if (new RegExp(`\\b${className}\\b`).test(contents)) {
                    offenders.push(`${file.slice(SRC.length + 1)} → ${className}`)
                }
            }
        }
        expect(offenders).toEqual([])
    })
})
