import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { MAX_UPLOAD_BYTES, csvConfigFor, isValidDelimiter, isValidTimestampFormat, normalizeDelimiter, previewStampsEqual } from '../src/features/imports/importUtils'

const SAMPLES = resolve(__dirname, '..', 'public', 'samples')

function load(name: string): string[][] {
    return readFileSync(join(SAMPLES, name), 'utf8')
        .trim()
        .split('\n')
        .map((line) => line.split(','))
}

describe('import sample files', () => {
    it('standard sample matches the wizard defaults', () => {
        const [header, ...rows] = load('standard-readings.csv')
        expect(header).toEqual(['meter_id', 'timestamp', 'energy_kwh', 'direction'])
        expect(rows.length).toBeGreaterThan(0)
        for (const row of rows) {
            expect(row).toHaveLength(4)
            expect(row[3]).toMatch(/^(in|out)$/)
            expect(Number(row[2])).not.toBeNaN()
        }
        const keys = rows.map((row) => `${row[0]}|${row[1]}|${row[3]}`)
        expect(new Set(keys).size).toBe(keys.length)
    })

    it('daily sample carries 96 quarter-hour slots', () => {
        const [header, ...rows] = load('daily-15min-profile.csv')
        expect(header.slice(0, 2)).toEqual(['meter_id', 'date'])
        expect(header.length).toBe(98)
        expect(header[2]).toBe('00:00')
        expect(header[header.length - 1]).toBe('23:45')
        for (const row of rows) {
            expect(row).toHaveLength(98)
            for (const value of row.slice(2)) {
                expect(Number(value)).not.toBeNaN()
            }
        }
    })

    it('samples reference the demo seed meters', () => {
        const meters = new Set(
            [...load('standard-readings.csv').slice(1), ...load('daily-15min-profile.csv').slice(1)].map(
                (row) => row[0],
            ),
        )
        expect(meters).toEqual(new Set(['CH-DEMO-CONS-0001', 'CH-DEMO-CONS-0002', 'CH-DEMO-PROD-0001']))
    })

    it('headed daily defaults resolve against the daily sample header', () => {
        const [header] = load('daily-15min-profile.csv')
        const cfg = csvConfigFor(true, 'daily_15min')
        expect(cfg.columnMap.meter_id).toBe('meter_id')
        expect(cfg.columnMap.timestamp).toBe('date')
        expect(header).toContain(cfg.columnMap.meter_id)
        expect(header).toContain(cfg.columnMap.timestamp)
        expect(header).toContain(cfg.columnMap.energy_start)
    })

    it('headed standard defaults resolve against the standard sample header', () => {
        const [header] = load('standard-readings.csv')
        const cfg = csvConfigFor(true, 'standard')
        for (const key of ['meter_id', 'timestamp', 'energy_kwh'] as const) {
            expect(header).toContain(cfg.columnMap[key])
        }
    })

    it('profile switch re-derives mappings instead of carrying stale ones', () => {
        const standard = csvConfigFor(true, 'standard')
        const daily = csvConfigFor(true, 'daily_15min')
        expect(standard.columnMap.timestamp).toBe('timestamp')
        expect(daily.columnMap.timestamp).toBe('date')
        expect(standard.columnMap.energy_start).not.toBe(daily.columnMap.energy_start)
    })

    it('preview stamp ignores numeric string padding ("096" vs "96")', () => {
        const base = {
            files: [{ name: 'a.csv', size: 10, lastModified: 1 }],
            source: 'csv',
            zevId: 'z1',
            hasHeader: true,
            delimiter: ',',
            formatProfile: 'daily_15min',
            timestampFormat: '%d.%m.%Y',
            intervalMinutes: '15',
            valuesCount: '96',
            overwriteExisting: false,
            columnMap: csvConfigFor(true, 'daily_15min').columnMap,
        }
        expect(previewStampsEqual({ ...base }, { ...base, valuesCount: '096' })).toBe(true)
        expect(previewStampsEqual({ ...base }, { ...base, valuesCount: '97' })).toBe(false)
    })

    it('preview stamp invalidates on non-numeric config ("96foo" vs "96")', () => {
        const base = {
            files: [{ name: 'a.csv', size: 10, lastModified: 1 }],
            source: 'csv',
            zevId: 'z1',
            hasHeader: true,
            delimiter: ',',
            formatProfile: 'daily_15min',
            timestampFormat: '%d.%m.%Y',
            intervalMinutes: '15',
            valuesCount: '96',
            overwriteExisting: false,
            columnMap: csvConfigFor(true, 'daily_15min').columnMap,
        }
        expect(previewStampsEqual({ ...base }, { ...base, valuesCount: '96foo' })).toBe(false)
        expect(previewStampsEqual({ ...base }, { ...base, intervalMinutes: '' })).toBe(false)
    })

    it('requires a weekday and matching year in week-based timestamp formats', () => {
        for (const format of ['%Y %U', '%Y %W', '%G %V', '%Y %V %u', '%%Y-%m-%d', '%Y %s']) {
            expect(isValidTimestampFormat(format), format).toBe(false)
        }
        for (const format of ['%Y %U %w', '%Y %W %a', '%G %V %u']) {
            expect(isValidTimestampFormat(format), format).toBe(true)
        }
    })

    it('timestamp format validation checks the full-date rule', () => {
        expect(isValidTimestampFormat('')).toBe(true)
        expect(isValidTimestampFormat('%d.%m.%Y')).toBe(true)
        expect(isValidTimestampFormat('%Y-%m-%dT%H:%M:%S%z')).toBe(true)
        expect(isValidTimestampFormat('%Y-%j')).toBe(true)
        expect(isValidTimestampFormat('garbage')).toBe(false)
        expect(isValidTimestampFormat('%d.%m')).toBe(false)
        expect(isValidTimestampFormat('%H:%M')).toBe(false)
    })

    it('delimiter validation accepts the backend tab escape', () => {
        expect(isValidDelimiter(',')).toBe(true)
        expect(isValidDelimiter(';')).toBe(true)
        expect(isValidDelimiter('\t')).toBe(true)
        expect(isValidDelimiter('\\t')).toBe(true)
        expect(isValidDelimiter(';;')).toBe(false)
        expect(isValidDelimiter('')).toBe(false)
        expect(normalizeDelimiter('\\t')).toBe('\t')
        expect(normalizeDelimiter(',')).toBe(',')
    })

    it('preview stamp treats tab escape and literal tab as equal', () => {
        const base = {
            files: [{ name: 'a.csv', size: 10, lastModified: 1 }],
            source: 'csv',
            zevId: 'z1',
            hasHeader: true,
            delimiter: ',',
            formatProfile: 'daily_15min',
            timestampFormat: '%d.%m.%Y',
            intervalMinutes: '15',
            valuesCount: '96',
            overwriteExisting: false,
            columnMap: csvConfigFor(true, 'daily_15min').columnMap,
        }
        expect(previewStampsEqual({ ...base }, { ...base, delimiter: '\\t' })).toBe(false)
        expect(previewStampsEqual({ ...base, delimiter: '\\t' }, { ...base, delimiter: '\t' })).toBe(true)
    })

    it('frontend upload cap mirrors the backend 50MB limit', () => {
        expect(MAX_UPLOAD_BYTES).toBe(50 * 1024 * 1024)
    })
})
