import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { act, createElement, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ImportLog, SdatReadingChange } from '../src/types/api'

import { en } from '../src/i18n/locales/en'
import { queryKeys } from '../src/lib/api/queryKeys'

const translate = vi.hoisted(() => vi.fn())

function localeHasKey(key: string): boolean {
    let node: unknown = en
    for (const part of key.split('.')) {
        if (typeof node !== 'object' || node === null || !(part in node)) return false
        node = (node as Record<string, unknown>)[part]
    }
    return typeof node === 'string'
}

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate }) }))
const heldApi = vi.hoisted(() => ({
    fetchHeldMeteringReadings: vi.fn(),
    fetchImportLog: vi.fn(),
}))
vi.mock('../src/lib/api/metering', () => ({
    fetchHeldMeteringReadings: heldApi.fetchHeldMeteringReadings,
    fetchImportLog: heldApi.fetchImportLog,
}))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return {
        ...actual,
        useAppSettings: () => ({ settings: {} }),
        formatDateTime: (value: string) => value,
    }
})

import { ImportProtocolModal } from '../src/features/imports/ImportProtocolModal'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function baseLog(overrides: Partial<ImportLog> = {}): ImportLog {
    return {
        id: 'log-1',
        batch_id: 'batch-1',
        zev: 'zev-1',
        zev_name: 'ZEV 1',
        imported_by_display: 'admin',
        filename: 'delivery.xml',
        rows_total: 96,
        rows_imported: 96,
        rows_overwritten: 0,
        rows_skipped: 0,
        source: 'sdatch',
        errors: [],
        warnings: [],
        created_at: '2026-03-10T09:00:00Z',
        ...overrides,
    }
}

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>
let queryClient: QueryClient

beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
    translate.mockClear()
    translate.mockImplementation((key: string, vars?: Record<string, unknown>) =>
        typeof vars?.defaultValue === 'string' && !localeHasKey(key) ? vars.defaultValue : key,
    )
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    heldApi.fetchHeldMeteringReadings.mockReset()
    heldApi.fetchHeldMeteringReadings.mockResolvedValue({ count: 0, page_size: 50, next: null, previous: null, results: [] })
    heldApi.fetchImportLog.mockReset()
    heldApi.fetchImportLog.mockResolvedValue(baseLog({ reading_changes: [] }))
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
    queryClient.clear()
})

function render(log: ImportLog | null, focusCorrections = false) {
    act(() => {
        root.render(
            createElement(
                QueryClientProvider,
                { client: queryClient },
                createElement(ImportProtocolModal, { log, focusCorrections, onClose: () => undefined }),
            ),
        )
    })
}


async function open(log: ImportLog, focusCorrections = false) {
    await act(async () => render(log, focusCorrections))
}

describe('ImportProtocolModal structured SDAT-CH rendering', () => {
    it('renders a mixed billable/held result from counters, not prose', () => {
        render(baseLog({
            result_status: 'accepted',
            result_counts: {
                created: 90, overwritten: 0, held: 4, promoted: 2, duplicate: 2,
                stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
            },
            issues: [
                { code: 'reactive_excluded', severity: 'info', message: 'backend prose', block_id: 'DOC-9', product: '8716867000047' },
            ],
            source_delivery: {
                delivery_id: 'DEL-1', creation: '2026-03-09T10:00:00Z', status: '9', reason: 'E88',
                sender_id: 'SENDER', sender_role: 'DSO', receiver_id: 'OPENZEV', receiver_role: 'ZEV',
            },
        }))
        const text = container.textContent ?? ''
        // Outcome + counters from structured fields.
        expect(text).toContain('pages.imports.protocol.outcome.accepted')
        expect(text).toContain('pages.imports.protocol.counts.created')
        expect(text).toContain('pages.imports.protocol.counts.held')
        expect(text).toContain('pages.imports.protocol.promotedNote')
        // Delivery identity and stable issue code with params.
        expect(text).toContain('DEL-1')
        expect(text).toContain('pages.imports.issues.reactive_excluded')
        expect(text).toContain('pages.imports.protocol.issueParam.block_id')
        expect(container.textContent).not.toContain('backend prose')
        expect(container.querySelector('details')).toBeNull()
        // Legacy CSV totals stay out of the structured view.
        expect(text).not.toContain('pages.imports.protocol.totalRows')
    })

    it('opens the held observations of this import, filtered to its batch', async () => {
        heldApi.fetchHeldMeteringReadings.mockResolvedValue({
            count: 2, page_size: 50, next: null, previous: null,
            results: ['METER-A', 'METER-B'].map((meter_id, index) => ({
                id: meter_id, meter_id,
                timestamp: `2026-10-25T0${index}:00:00Z`, direction: 'in', energy_kwh: '1.0000',
                condition: '21', accepted_energy_kwh: null, business_reason: 'E88',
                source_delivery_id: 'DELIVERY', source_document_id: `DOCUMENT-${index}`,
                source_creation: null, created_at: '2026-10-26T00:00:00Z',
            })),
        })
        await open(baseLog({
            result_status: 'accepted',
            batch_id: 'batch-42',
            result_counts: {
                created: 90, overwritten: 0, held: 4, promoted: 0, duplicate: 0,
                stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
            },
            issues: [],
        }))
        const text = container.textContent ?? ''
        expect(text).toContain('pages.imports.protocol.heldTitle')
        expect(heldApi.fetchHeldMeteringReadings).toHaveBeenCalledWith(
            expect.objectContaining({ importBatch: 'batch-42' }),
        )
        await vi.waitFor(() => expect(container.textContent).toContain('METER-B'))
        expect(container.textContent).toContain('METER-A')
        expect(container.textContent).toContain('DELIVERY')
        expect(container.textContent).toContain('DOCUMENT-0')
        expect(container.textContent).toContain('DOCUMENT-1')
        expect(container.textContent).toContain('GMT+02:00')
        expect(container.textContent).toContain('GMT+01:00')
    })

    it('keeps a held-only accepted result distinct from a rejection', () => {
        render(baseLog({
            result_status: 'held',
            rows_imported: 0,
            result_counts: {
                created: 0, overwritten: 0, held: 4, promoted: 0, duplicate: 0,
                stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
            },
            issues: [],
        }))
        const text = container.textContent ?? ''
        expect(text).toContain('pages.imports.protocol.outcome.held')
        expect(text).not.toContain('pages.imports.protocol.outcome.rejected')
    })

    it('marks a correction-only result successful with zero new rows', () => {
        render(baseLog({
            result_status: 'accepted',
            result_counts: {
                created: 0, overwritten: 4, held: 0, promoted: 4, duplicate: 0,
                stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
            },
            issues: [],
        }))
        expect(container.textContent).toContain('pages.imports.protocol.outcome.correctionOnly')
        expect(container.querySelector('header .error-text')).toBeNull()
        expect(container.querySelector('header h3')?.textContent).toBe('delivery.xml')
        const history = container.querySelector('#correction-history')!
        const technical = [...container.querySelectorAll('section')].find(section => section.textContent?.includes('pages.imports.protocol.batchId'))!
        expect(history.compareDocumentPosition(technical) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    })

    it('renders an identical replay as unchanged and a bad file as rejected', () => {
        render(baseLog({
            result_status: 'unchanged',
            rows_imported: 0,
            result_counts: {
                created: 0, overwritten: 0, held: 0, promoted: 0, duplicate: 96,
                stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
            },
            issues: [{ code: 'duplicate_delivery', severity: 'info', message: 'already there', duplicate: 96 }],
        }))
        expect(container.textContent).toContain('pages.imports.protocol.outcome.unchanged')

        render(baseLog({
            result_status: 'rejected',
            rows_imported: 0,
            result_counts: {
                created: 0, overwritten: 0, held: 0, promoted: 0, duplicate: 0,
                stale: 0, excluded: 0, rejected: 96, quarantine_overwritten: 0,
            },
            issues: [{ code: 'unknown_meter', severity: 'error', message: 'no such meter', meter_id: 'CH-X', block_id: 'DOC-1' }],
        }))
        const text = container.textContent ?? ''
        expect(text).toContain('pages.imports.protocol.outcome.rejected')
        expect(container.querySelector('header .error-text')?.textContent).toContain('pages.imports.protocol.outcome.rejected')
        expect(text).toContain('pages.imports.issues.unknown_meter')
        expect(text).toContain('pages.imports.protocol.issueParam.meter_id')
    })

    it('reports an unsupported profile by code with resolution details', () => {
        render(baseLog({
            result_status: 'rejected',
            rows_imported: 0,
            result_counts: {
                created: 0, overwritten: 0, held: 0, promoted: 0, duplicate: 0,
                stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
            },
            issues: [{ code: 'unsupported_reason', severity: 'error', message: 'C40 LEG', reason: 'C40' }],
        }))
        const text = container.textContent ?? ''
        expect(text).toContain('pages.imports.issues.unsupported_reason')
        expect(text).toContain('pages.imports.protocol.issueParam.reason')
    })

    it('uses a localized fallback instead of raw backend prose for unmapped codes', () => {
        render(baseLog({
            result_status: 'rejected',
            rows_imported: 0,
            issues: [{ code: 'future_code', severity: 'error', message: 'Some new backend detail.' }],
        }))
        const text = container.textContent ?? ''
        expect(text).toContain('pages.imports.issues.unknownCode')
        expect(text).not.toContain('Some new backend detail.')
    })

    it('explains quarantine-replacement protection distinctly', () => {
        render(baseLog({
            result_status: 'accepted',
            result_counts: {
                created: 0, overwritten: 0, held: 4, promoted: 0, duplicate: 0,
                stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 4,
            },
            deletable: false,
            deletion_protection_code: 'quarantine_replace_protected',
            issues: [],
        }))
        expect(container.textContent).toContain('pages.imports.delete.quarantineProtected')
    })

    it('keeps the legacy CSV rendering without structured metadata', () => {
        render(baseLog({
            source: 'csv',
            rows_total: 10,
            rows_imported: 9,
            rows_skipped: 1,
            warnings: [{ row: null, warning: 'Overwrote 1 existing reading.' }],
            errors: [{ row: 2, meter_id: 'M-9', error: 'Duplicate reading' }],
        }))
        const text = container.textContent ?? ''
        expect(text).toContain('pages.imports.protocol.totalRows')
        expect(text).toContain('Overwrote 1 existing reading.')
        expect(text).toContain('M-9')
        expect(text).not.toContain('pages.imports.protocol.outcome.accepted')
        expect(container.querySelector('.data-table-sort')).toBeNull()
        expect(container.querySelector('ul, li')).toBeNull()
    })
})

describe('ImportProtocolModal correction history', () => {
    it('shares the pending detail request across a StrictMode remount', async () => {
        let resolve!: (value: ImportLog) => void
        heldApi.fetchImportLog.mockReturnValue(new Promise<ImportLog>(done => { resolve = done }))
        await act(async () => root.render(createElement(StrictMode, null,
            createElement(QueryClientProvider, { client: queryClient },
                createElement(ImportProtocolModal, { log: baseLog(), onClose: () => undefined }),
            ),
        )))
        expect(heldApi.fetchImportLog).toHaveBeenCalledTimes(1)
        await act(async () => resolve(baseLog({ reading_changes: [] })))
    })

    it('does not let a cancelled request clear a later session’s cached history', async () => {
        let reject!: (error: unknown) => void
        heldApi.fetchImportLog.mockReturnValueOnce(new Promise<ImportLog>((_resolve, fail) => { reject = fail }))
        await open(baseLog())
        await act(async () => render(null))
        await queryClient.cancelQueries()
        queryClient.clear()
        const replacement = baseLog({ reading_changes: [change({ new_energy: '3.0000' })] })
        queryClient.setQueryData(queryKeys.metering.importLog('log-1'), replacement)
        await act(async () => reject({ response: { status: 403 } }))
        expect(queryClient.getQueryData(queryKeys.metering.importLog('log-1'))).toEqual(replacement)
    })

    it('retains loaded history after a transient refresh failure and offers retry', async () => {
        const detail = baseLog({ reading_changes: [change()] })
        heldApi.fetchImportLog.mockResolvedValue(detail)
        await open(baseLog())
        await vi.waitFor(() => expect(container.textContent).toContain('1.2500 kWh'))
        heldApi.fetchImportLog.mockRejectedValueOnce({ response: { status: 503 } })
        await act(async () => {
            await queryClient.invalidateQueries({ queryKey: queryKeys.metering.importLog('log-1') })
        })
        expect(container.textContent).toContain('1.2500 kWh')
        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsRefreshFailed'))
        let resolve!: (value: ImportLog) => void
        heldApi.fetchImportLog.mockReturnValueOnce(new Promise<ImportLog>(done => { resolve = done }))
        act(() => Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'common.retry')!.click())
        await vi.waitFor(() => expect(Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'common.retry')?.disabled).toBe(true))
        await act(async () => resolve(detail))
        await vi.waitFor(() => expect(container.textContent).not.toContain('pages.imports.protocol.correctionsRefreshFailed'))
    })

    it.each([401, 403, 404])('hides cached history after access/deletion response %s', async (status) => {
        heldApi.fetchImportLog.mockResolvedValue(baseLog({ reading_changes: [change()] }))
        await open(baseLog())
        await vi.waitFor(() => expect(container.textContent).toContain('1.2500 kWh'))
        heldApi.fetchImportLog.mockRejectedValue({ response: { status } })
        await act(async () => {
            await queryClient.invalidateQueries({ queryKey: queryKeys.metering.importLog('log-1') })
        })
        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsUnavailable'))
        expect(container.textContent).not.toContain('1.2500 kWh')
        expect(queryClient.getQueryData(queryKeys.metering.importLog('log-1'))).toBeNull()
        heldApi.fetchImportLog.mockRejectedValue(new Error('offline'))
        await act(async () => render(null))
        await open(baseLog())
        await act(async () => Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'common.retry')!.click())
        await vi.waitFor(() => expect(queryClient.isFetching()).toBe(0))
        await vi.waitFor(() => expect(Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'common.retry')?.disabled).toBe(false))
        expect(container.textContent).not.toContain('1.2500 kWh')
        heldApi.fetchImportLog.mockResolvedValue(baseLog({ reading_changes: [change()] }))
        await act(async () => Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'common.retry')!.click())
        await vi.waitFor(() => expect(container.textContent).toContain('1.2500 kWh'))
    })

    it('retries an initial detail failure', async () => {
        heldApi.fetchImportLog.mockRejectedValueOnce(new Error('offline'))
        await open(baseLog())
        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsUnavailable'))
        let resolve!: (value: ImportLog) => void
        heldApi.fetchImportLog.mockReturnValueOnce(new Promise<ImportLog>(done => { resolve = done }))
        const retry = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'common.retry')!
        act(() => retry.click())
        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsLoading'))
        await act(async () => resolve(baseLog({ reading_changes: [change()] })))
        await vi.waitFor(() => expect(container.textContent).toContain('1.2500 kWh'))
    })

    it('does not steal focus when a slow detail request finishes', async () => {
        let resolve!: (value: ImportLog) => void
        heldApi.fetchImportLog.mockReturnValueOnce(new Promise<ImportLog>(done => { resolve = done }))
        await open(baseLog(), true)
        const close = container.querySelector<HTMLButtonElement>('.form-modal-close')!
        close.focus()
        await act(async () => resolve(baseLog({ reading_changes: [change()] })))
        await vi.waitFor(() => expect(container.textContent).toContain('1.2500 kWh'))
        await act(async () => { await new Promise(requestAnimationFrame) })
        expect(document.activeElement).toBe(close)
        expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
    })

    function change(overrides: Partial<SdatReadingChange> = {}): SdatReadingChange {
        return {
            metering_point: 'mp-1',
            meter_id: 'CH-1',
            timestamp: '2026-03-02T00:15:00Z',
            direction: 'in' as const,
            kind: 'value' as const,
            old_energy: '1.2500',
            new_energy: '2.5000',
            promoted: false,
            source_document_id: 'BLOCK-9',
            ...overrides,
        }
    }

    it('reads the import detail when the protocol opens from list data', async () => {
        heldApi.fetchImportLog.mockResolvedValue(baseLog({ reading_changes: [] }))
        await open(baseLog())

        expect(heldApi.fetchImportLog).toHaveBeenCalledWith('log-1')
        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsTitle'))
    })

    it('renders each recorded change kind with its values and provenance', async () => {
        heldApi.fetchImportLog.mockResolvedValue(baseLog({
            reading_changes: [
                change(),
                change({ kind: 'availability', timestamp: '2026-03-02T00:30:00Z', old_energy: null, new_energy: '0.0000', promoted: true }),
                change({ kind: 'metadata', timestamp: '2026-03-02T00:45:00Z', new_energy: '1.2500', source_document_id: '' }),
            ],
        }))
        await open(baseLog())

        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsRetained'))
        const text = container.textContent ?? ''
        expect(text).toContain('pages.imports.protocol.corrections.kinds.value')
        expect(text).toContain('pages.imports.protocol.corrections.kinds.availability')
        expect(text).toContain('pages.imports.protocol.corrections.kinds.metadata')
        expect(text).toContain('1.2500 kWh')
        expect(text).toContain('2.5000 kWh')
        // A missing previous value is named, never shown as zero.
        expect(text).toContain('pages.imports.protocol.corrections.noPreviousValue')
        expect(text).toContain('0.0000 kWh')
        expect(text).toContain('pages.imports.protocol.corrections.promoted')
        expect(text).toContain('BLOCK-9')
        // Metadata before/after is not persisted, and the protocol says so.
        expect(text).toContain('pages.imports.protocol.corrections.metadataNotRecorded')
    })

    it('preserves decimal strings, zero old values and repeated Swiss-hour offsets', async () => {
        heldApi.fetchImportLog.mockResolvedValue(baseLog({
            reading_changes: [
                change({ timestamp: '2026-10-25T00:00:00Z', old_energy: '0.0000', new_energy: '123456789012.123456' }),
                change({ timestamp: '2026-10-25T01:00:00Z', direction: 'out', new_energy: '0.000001' }),
            ],
        }))
        await open(baseLog())
        await vi.waitFor(() => expect(container.textContent).toContain('123456789012.123456 kWh'))
        expect(container.textContent).toContain('0.0000 kWh')
        expect(container.textContent).toContain('0.000001 kWh')
        expect(container.textContent).toContain('GMT+02:00')
        expect(container.textContent).toContain('GMT+01:00')
        expect(container.textContent).toContain('pages.imports.preview.directionOut')
    })

    it('says nothing changed energy when every retained event is metadata', async () => {
        heldApi.fetchImportLog.mockResolvedValue(baseLog({
            reading_changes: [
                change({ kind: 'metadata', new_energy: '1.2500' }),
                change({ kind: 'metadata', new_energy: '1.2500', timestamp: '2026-03-02T01:00:00Z' }),
            ],
        }))
        await open(baseLog())

        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsRetained'))
        expect(container.textContent).toContain('pages.imports.protocol.correctionsMetadataOnly')
        expect(container.textContent).toContain('pages.imports.protocol.corrections.metadataNotRecorded')
    })

    it('warns about an incomplete history even when no change was retained', async () => {
        heldApi.fetchImportLog.mockResolvedValue(baseLog({
            result_status: 'accepted',
            reading_changes: [],
            result_counts: {
                created: 96, overwritten: 96, held: 0, promoted: 0, duplicate: 0,
                stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
                reading_changes_truncated: true,
            },
        }))
        await open(baseLog())

        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsTruncated'))
        // No fabricated omitted count: the boolean is all the backend records.
        expect(container.textContent).toContain('pages.imports.protocol.correctionsNoneRecorded')
        expect(translate).toHaveBeenCalledWith('pages.imports.protocol.correctionsRetained', { count: 0 })
        expect(container.textContent).not.toContain('pages.imports.protocol.correctionsNoChangesConfirmed')
    })

    it('separates a confirmed no-op from CSV and legacy imports without recorded history', async () => {
        heldApi.fetchImportLog.mockResolvedValue(baseLog({ result_status: 'unchanged', reading_changes: [] }))
        await open(baseLog())
        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsNoChangesConfirmed'))
        expect(container.textContent).not.toContain('pages.imports.protocol.correctionsNoneRecorded')

        // A different log id, so the second render cannot reuse the first's cache.
        heldApi.fetchImportLog.mockResolvedValue(baseLog({ id: 'log-2', source: 'csv', reading_changes: [] }))
        await open(baseLog({ id: 'log-2', source: 'csv' }))
        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsNoneRecorded'))
        expect(container.textContent).not.toContain('pages.imports.protocol.correctionsNoChangesConfirmed')

        heldApi.fetchImportLog.mockResolvedValue(baseLog({ id: 'legacy', reading_changes: undefined }))
        await open(baseLog({ id: 'legacy' }))
        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsNoneRecorded'))
        expect(container.textContent).not.toContain('pages.imports.protocol.correctionsNoChangesConfirmed')
    })

    it('renders CSV changes without SDAT delivery provenance', async () => {
        const log = baseLog({ source: 'csv', reading_changes: [change({ promoted: false, source_document_id: '' })] })
        heldApi.fetchImportLog.mockResolvedValue(log)
        await open(baseLog({ source: 'csv' }))
        await vi.waitFor(() => expect(container.textContent).toContain('1.2500 kWh'))
        expect(container.textContent).not.toContain('pages.imports.protocol.delivery.deliveryId')
        expect(container.textContent).not.toContain('pages.imports.protocol.corrections.promoted')
    })

    it('keeps a known truncation warning when the detail is inaccessible', async () => {
        heldApi.fetchImportLog.mockRejectedValue({ response: { status: 404 } })
        await open(baseLog({ result_counts: {
            created: 0, overwritten: 0, held: 0, promoted: 0, duplicate: 0,
            stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
            reading_changes_truncated: true,
        } }))
        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsUnavailable'))
        expect(container.textContent).toContain('pages.imports.protocol.correctionsTruncated')
        expect(container.querySelectorAll('#correction-history tbody tr')).toHaveLength(0)
    })

    it('renders a large retained history one bounded page at a time', async () => {
        const many = Array.from({ length: 10_000 }, (_, index) =>
            change({
                timestamp: new Date(Date.parse('2026-03-02T00:00:00Z') + index * 900_000).toISOString(),
                old_energy: `${index}.0000`,
                new_energy: `${index + 1}.0000`,
            }),
        )
        heldApi.fetchImportLog.mockResolvedValue(baseLog({ reading_changes: many }))
        await open(baseLog())

        await vi.waitFor(() => expect(container.textContent).toContain('pages.imports.protocol.correctionsRetained'))
        const rows = container.querySelectorAll('#correction-history tbody tr')
        expect(rows).toHaveLength(50)
        expect(container.textContent).toContain('1 / 200')
        // The retained count is the array length; the omitted count stays unknown.
        expect(translate).toHaveBeenCalledWith('pages.imports.protocol.correctionsRetained', { count: 10000 })
        act(() => container.querySelector<HTMLButtonElement>('#correction-history button[aria-label="common.pagination.next"]')!.click())
        expect(container.querySelectorAll('#correction-history tbody tr')).toHaveLength(50)
        expect(container.querySelector('#correction-history tbody tr')?.textContent).toContain('50.0000 kWh')
        expect(container.textContent).toContain('2 / 200')

        act(() => container.querySelectorAll<HTMLButtonElement>('#correction-history th button')[4].click())
        expect(container.querySelector('#correction-history tbody tr')?.textContent).toContain('9950.0000 kWh')
        expect(container.querySelectorAll('#correction-history tbody tr')).toHaveLength(50)

        heldApi.fetchImportLog.mockResolvedValue(baseLog({ id: 'another', reading_changes: [change()] }))
        await open(baseLog({ id: 'another' }))
        await vi.waitFor(() => expect(translate).toHaveBeenCalledWith('pages.imports.protocol.correctionsRetained', { count: 1 }))
        expect(container.querySelectorAll('#correction-history tbody tr')).toHaveLength(1)
        expect(container.textContent).not.toContain('2 / 200')
    })
})
