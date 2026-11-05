import { describe, expect, it } from 'vitest'
import {
    SDAT_UPLOAD_ACCEPT,
    importLogProtectionCode,
    isFailedBatchOutcome,
    isImportLogDeletable,
    isSdatLog,
    sdatIssueParams,
    sdatOutcomeKind,
} from '../src/features/imports/sdatOutcome'
import type { ImportLog } from '../src/types/api'

function log(overrides: Partial<ImportLog> = {}): ImportLog {
    return {
        id: 'log-1',
        filename: 'delivery.xml',
        rows_imported: 0,
        rows_overwritten: 0,
        rows_skipped: 0,
        source: 'sdatch',
        deletable: true,
        deletion_protection_code: null,
        created_at: '2026-03-10T09:00:00Z',
        ...overrides,
    }
}

describe('importLogProtectionCode', () => {
    it('is null for an additive import', () => {
        expect(importLogProtectionCode(log({ rows_overwritten: 0, result_counts: {} }))).toBeNull()
        expect(isImportLogDeletable(log({ rows_overwritten: 0, result_counts: {} }))).toBe(true)
    })

    it('reports billable replacements as overwrite-protected', () => {
        expect(importLogProtectionCode(log({ rows_overwritten: 3, deletable: false, deletion_protection_code: 'overwrite_import_protected' }))).toBe('overwrite_import_protected')
        expect(isImportLogDeletable(log({ rows_overwritten: 3, deletable: false, deletion_protection_code: 'overwrite_import_protected' }))).toBe(false)
    })

    it('reports held replacements as quarantine-protected', () => {
        expect(
            importLogProtectionCode(log({ rows_overwritten: 0, deletable: false, deletion_protection_code: 'quarantine_replace_protected' })),
        ).toBe('quarantine_replace_protected')
    })

    it('uses the server code and its deletable flag', () => {
        expect(
            importLogProtectionCode(log({ rows_overwritten: 0, deletable: false, deletion_protection_code: 'quarantine_replace_protected' })),
        ).toBe('quarantine_replace_protected')
        expect(
            importLogProtectionCode(log({ rows_overwritten: 0, deletable: true, deletion_protection_code: null })),
        ).toBeNull()
    })
})

describe('sdatOutcomeKind', () => {
    it('classifies the four machine-readable outcomes without reading prose', () => {
        expect(sdatOutcomeKind(log({ result_status: 'rejected' }))).toBe('rejected')
        expect(sdatOutcomeKind(log({ result_status: 'held' }))).toBe('held')
        expect(sdatOutcomeKind(log({ result_status: 'unchanged' }))).toBe('unchanged')
        expect(sdatOutcomeKind(log({
            result_status: 'accepted',
            result_counts: { created: 10, overwritten: 0 } as ImportLog['result_counts'],
        }))).toBe('accepted')
    })

    it('treats accepted overwrites without new rows as correction-only', () => {
        expect(sdatOutcomeKind(log({
            result_status: 'accepted',
            result_counts: { created: 0, overwritten: 4, promoted: 4 } as ImportLog['result_counts'],
            // Promotion is a subset, not extra energy/counts: it must not
            // flip the classification back to plain accepted.
        }))).toBe('correctionOnly')
    })

    it('falls back to legacy without structured metadata', () => {
        expect(sdatOutcomeKind(log({ source: 'csv' }))).toBe('legacy')
        expect(isSdatLog(log({ source: 'csv' }))).toBe(false)
        expect(isSdatLog(log({ result_status: 'accepted' }))).toBe(true)
    })
})

describe('isFailedBatchOutcome', () => {
    it('treats thrown errors and rejected 201 logs as failed', () => {
        const file = new File(['x'], 'a.xml')
        expect(isFailedBatchOutcome({ file, value: null, error: new Error('boom') })).toBe(true)
        expect(isFailedBatchOutcome({ file, value: log({ result_status: 'rejected' }), error: null })).toBe(true)
    })

    it('treats accepted, held and unchanged 201 logs as successful', () => {
        const file = new File(['x'], 'a.xml')
        for (const result_status of ['accepted', 'held', 'unchanged'] as const) {
            expect(isFailedBatchOutcome({ file, value: log({ result_status }), error: null })).toBe(false)
        }
    })
})

describe('sdatIssueParams', () => {
    it('renders structured params in display order and shortens arrays', () => {
        const params = sdatIssueParams({
            code: 'missing_position',
            severity: 'error',
            message: 'Block is incomplete.',
            meter_id: 'CH-M-1',
            position: 5,
            missing: [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
            block_id: 'DOC-1',
            unexpected_extra: 'stays in the message',
        })
        expect(params.map((entry) => entry.key)).toEqual(['meter_id', 'block_id', 'position', 'missing'])
        expect(params.find((entry) => entry.key === 'missing')?.value).toBe('5, 6, 7, 8, 9, 10, 11, 12, 13, 14 (+1)')
    })

    it('renders tariff-band and support correlation fields', () => {
        expect(sdatIssueParams({ code: 'unsupported_feature', severity: 'error', message: 'Unsupported', feature: 'E11', import_log_id: 'LOG-1' }))
            .toEqual([{ key: 'feature', value: 'E11' }, { key: 'import_log_id', value: 'LOG-1' }])
    })

    it('keeps the total missing count when the displayed position list is shortened', () => {
        const params = sdatIssueParams({ code: 'missing_position', severity: 'error', message: 'Missing positions',
            expected_positions: 100, missing_count: 80, missing: Array.from({ length: 50 }, (_, index) => index + 1) })
        expect(params).toEqual([
            { key: 'expected_positions', value: '100' },
            { key: 'missing_count', value: '80' },
            { key: 'missing', value: '1, 2, 3, 4, 5, 6, 7, 8, 9, 10 (+40)' },
        ])
    })

    it('skips empty and non-scalar params', () => {
        expect(sdatIssueParams({ code: 'x', severity: 'error', message: 'm', meter_id: '', block_id: null, missing: [] })).toEqual([])
    })
})

describe('SDAT_UPLOAD_ACCEPT', () => {
    it('accepts plain and gzipped XML', () => {
        expect(SDAT_UPLOAD_ACCEPT).toContain('.xml')
        expect(SDAT_UPLOAD_ACCEPT).toContain('.gz')
    })
})
