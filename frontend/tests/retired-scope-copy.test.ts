import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

const SRC = resolve(__dirname, '../src')

function sourceFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name)
        if (entry.isDirectory()) return sourceFiles(path)
        return /\.tsx?$/.test(entry.name) ? [path] : []
    })
}

function rel(path: string): string {
    return path.slice(SRC.length + 1)
}

describe('retired scope advice', () => {
    it('does not re-introduce the retired select-a-ZEV advice', () => {
        const RETIRED = ['pages.dashboard.selectZev', 'pages.dashboard.noZev',
                         'pages.invoices.selectZev', 'pages.zevSettings.selectZev',
                         'pages.reports.selectZevTitle', 'pages.reports.noZevTitle',
                         'pages.reports.selectZevDescription', 'pages.reports.noZevDescription']
        const offenders: string[] = []
        for (const file of sourceFiles(SRC)) {
            const contents = readFileSync(file, 'utf8')
            for (const key of RETIRED) {
                const escaped = key.replaceAll('.', '\\.')
                if (new RegExp(`["'\u0060]${escaped}["'\u0060]`).test(contents)) offenders.push(`${rel(file)} → ${key}`)
            }
        }
        expect(offenders).toEqual([])
    })
})
