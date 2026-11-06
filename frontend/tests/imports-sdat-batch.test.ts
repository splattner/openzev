import { QueryClient } from '@tanstack/react-query'
import { queryKeys } from '../src/lib/api/queryKeys'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ImportLog } from '../src/types/api'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

type MutationVariables = {
    files?: File[]
    scope: { selectedZevId: string | null; canWrite: boolean; accountId?: number; scopeKey?: string }
    id?: string
}
type MutationOptions = { onSuccess: (data: unknown, variables: MutationVariables) => void }
const mutateCalls: Array<{ vars: MutationVariables; opts?: unknown }> = []
const mutationOptions: MutationOptions[] = []
const pushToast = vi.fn()
const translate = vi.fn((key: string) => key)

let cacheClient: QueryClient

vi.mock('@tanstack/react-query', async importOriginal => ({
    ...await importOriginal(),
    useQueryClient: () => cacheClient,
    useQuery: () => ({ data: cacheClient.getQueryData<ImportLog[]>(queryKeys.metering.importLogs()) ?? importLogsData, isLoading: false, isError: false, error: null, refetch: vi.fn() }),
    useMutation: (options: MutationOptions) => {
        mutationOptions.push(options)
        return {
            isPending: false,
            mutate: (vars: MutationVariables, opts?: unknown) => {
                cacheClient.setQueryData(queryKeys.metering.importLogs(), importLogsData)
                mutateCalls.push({ vars, opts })
            },
        }
    },
}))
vi.mock('../src/components/CivilDateInput', () => ({
    CivilDateInput: ({ value, onChange }: { value: string; onChange: (value: string) => void }) =>
        createElement('input', { type: 'date', value, onChange: (event: React.ChangeEvent<HTMLInputElement>) => onChange(event.target.value) }),
}))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1, role: 'admin' } }) }))
vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => ({ selectedZevId: 'zev-1', selectedZev: { id: 'zev-1', name: 'ZEV 1' } }),
    useOptionalManagedZev: () => ({ selectedZevId: 'zev-1', selectedZev: { id: 'zev-1', name: 'ZEV 1' } }),
}))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatDateTime: (value: string) => value,
    formatShortDate: (value: string) => value,
}))
vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: translate }),
}))
vi.mock('../src/lib/toast', () => ({
    useToast: () => ({ pushToast }),
}))

import { ImportsPage } from '../src/pages/ImportsPage'

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>
let importLogsData: ImportLog[] = []
let router: ReturnType<typeof createMemoryRouter>

function buttons(label: string): HTMLButtonElement[] {
    return Array.from(container.querySelectorAll('button')).filter(
        (button) => button.textContent === label || button.getAttribute('aria-label') === label,
    ) as HTMLButtonElement[]
}

function sdatLog(overrides: Partial<ImportLog> = {}): ImportLog {
    return {
        id: 'log-1',
        batch_id: 'batch-1',
        zev: 'zev-1',
        created_at: '2026-03-10T09:00:00Z',
        source: 'sdatch',
        filename: 'delivery.xml',
        rows_total: 96,
        rows_imported: 96,
        rows_overwritten: 0,
        rows_skipped: 0,
        errors: [],
        warnings: [],
        result_status: 'accepted',
        result_counts: {
            created: 96, overwritten: 0, held: 0, promoted: 0, duplicate: 0,
            stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
        },
        issues: [],
        deletable: true,
        deletion_protection_code: null,
        ...overrides,
    }
}

function renderPage() {
    router = createMemoryRouter([
        { path: '/metering/imports', element: createElement(ImportsPage) },
        { path: '/elsewhere', element: createElement('p', null, 'Elsewhere') },
    ], { initialEntries: ['/metering/imports'] })
    act(() => {
        root.render(
            createElement(MantineProvider, null,
                createElement(RouterProvider, { router })),
        )
    })
}

function openWizard() {
    act(() => {
        buttons('pages.imports.actions.newImport')[0].click()
    })
}

function selectSdatch() {
    const select = container.querySelector('select') as HTMLSelectElement
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
    act(() => {
        setter.call(select, 'sdatch')
        select.dispatchEvent(new Event('change', { bubbles: true }))
    })
}

function pick(...names: string[]) {
    const input = container.querySelector('input[type=file]') as HTMLInputElement
    const picked = names.map((name) => new File(['<x/>'], name, { type: 'text/xml' }))
    Object.defineProperty(input, 'files', { value: picked, configurable: true })
    act(() => {
        input.dispatchEvent(new Event('change', { bubbles: true }))
    })
}

function goToStep2WithFiles(...names: string[]) {
    openWizard()
    // Real pointer input arms FormModal's unsaved-control snapshot.
    container.querySelector('select')!.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    selectSdatch()
    pick(...names)
    act(() => {
        buttons('pages.imports.wizard.nextConfig')[0].click()
    })
}

function startImport() {
    act(() => {
        buttons('pages.imports.wizard.startImport')[0].click()
    })
}

/** Resolve the upload mutation with one outcome per file. */
function resolveUpload(outcomes: Array<{ file: File; value: unknown; error: unknown }>) {
    act(() => {
        mutationOptions[1].onSuccess(outcomes, mutateCalls[mutateCalls.length - 1].vars)
    })
}

function uploadFiles(): File[] {
    return mutateCalls[mutateCalls.length - 1].vars.files ?? []
}

beforeEach(() => {
    cacheClient = new QueryClient()
    mutateCalls.length = 0
    mutationOptions.length = 0
    importLogsData = []
    pushToast.mockClear()
    translate.mockClear()
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        configurable: true,
        value: (query: string) => ({
            matches: false,
            media: query,
            onchange: null,
            addListener: () => undefined,
            removeListener: () => undefined,
            addEventListener: () => undefined,
            removeEventListener: () => undefined,
            dispatchEvent: () => false,
        }),
    })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    renderPage()
})

afterEach(() => {
    act(() => root.unmount())
    cacheClient.clear()
    container.remove()
})

describe('ImportsPage SDAT-CH batch outcomes', () => {
    it('accepts gzipped deliveries in the picker', () => {
        openWizard()
        selectSdatch()
        const input = container.querySelector('input[type=file]') as HTMLInputElement
        expect(input.accept).toContain('.gz')
        pick('delivery.xml.gz')
        expect(buttons('pages.imports.wizard.nextConfig')[0].disabled).toBe(false)
    })

    it('keeps only the rejected file selected after a mixed batch', () => {
        goToStep2WithFiles('good.xml', 'bad.xml')
        startImport()
        const files = uploadFiles()
        resolveUpload([
            { file: files[0], value: sdatLog({ id: 'log-good', filename: 'good.xml' }), error: null },
            {
                file: files[1],
                value: sdatLog({
                    id: 'log-bad',
                    filename: 'bad.xml',
                    rows_imported: 0,
                    result_status: 'rejected',
                    issues: [{ code: 'unknown_meter', severity: 'error', message: 'no such meter', meter_id: 'CH-X' }],
                }),
                error: null,
            },
        ])
        // The rejected 201 log failed semantically: partial toast names it…
        expect(pushToast).toHaveBeenCalledWith('pages.imports.messages.importBatchPartial', 'error')
        expect(translate).toHaveBeenCalledWith('pages.imports.messages.importBatchPartial', {
            done: 1, total: 2, failed: 1, names: 'bad.xml', imported: 96, overwritten: 0, held: 0,
        })
        // …its protocol opens without treating that URL update as discarding the draft.
        expect(router.state.location.search).toBe('?import=log-bad')
        expect(container.textContent).not.toContain('common.unsavedChanges.title')
        expect(container.textContent).toContain('pages.imports.protocol.title')
        expect(container.textContent).toContain('pages.imports.protocol.outcome.rejected')
        startImport()
        expect(uploadFiles().map((file) => file.name)).toEqual(['bad.xml'])
    })

    it('opens the protocol with a rejected notice for a single rejected file', () => {
        goToStep2WithFiles('bad.xml')
        startImport()
        const files = uploadFiles()
        resolveUpload([
            {
                file: files[0],
                value: sdatLog({
                    rows_imported: 0,
                    result_status: 'rejected',
                    issues: [{ code: 'missing_position', severity: 'error', message: 'incomplete', block_id: 'DOC-1' }],
                }),
                error: null,
            },
        ])
        expect(router.state.location.search).toBe('?import=log-1')
        expect(container.textContent).not.toContain('common.unsavedChanges.title')
        expect(pushToast).toHaveBeenCalledWith('pages.imports.messages.importSdatRejected', 'error')
        expect(container.textContent).toContain('pages.imports.protocol.title')
        // A rejected file wrote nothing: the wizard stays open for a retry.
        expect(container.textContent).toContain('pages.imports.wizard.title')
    })

    it('opens a held-only protocol without relying on legacy warnings', () => {
        goToStep2WithFiles('held.xml')
        startImport()
        const files = uploadFiles()
        resolveUpload([
            {
                file: files[0],
                value: sdatLog({
                    rows_imported: 0,
                    result_status: 'held',
                    result_counts: {
                        created: 0, overwritten: 0, held: 4, promoted: 0, duplicate: 0,
                        stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 0,
                    },
                }),
                error: null,
            },
        ])
        expect(router.state.location.search).toBe('?import=log-1')
        expect(container.textContent).not.toContain('common.unsavedChanges.title')
        expect(pushToast).toHaveBeenCalledWith('pages.imports.messages.importSdat_held', 'success')
        expect(container.textContent).not.toContain('pages.imports.wizard.title')
        expect(container.textContent).toContain('pages.imports.protocol.outcome.held')
    })
})

it.each([false, true])('still protects a rejected-file draft with protocol closed=%s', async (closeProtocol) => {
    goToStep2WithFiles('bad.xml')
    startImport()
    resolveUpload([{ file: uploadFiles()[0], value: sdatLog({ result_status: 'rejected' }), error: null }])
    await act(async () => undefined)
    expect(router.state.location.search).toBe('?import=log-1')
    if (closeProtocol) {
        const protocol = Array.from(container.querySelectorAll('[role=dialog]')).find(dialog =>
            dialog.querySelector('h2')?.textContent === 'pages.imports.protocol.title',
        )!
        await act(async () => (protocol.querySelector('.form-modal-close') as HTMLButtonElement).click())
        expect(router.state.location.search).toBe('')
    }
    await act(async () => { void router.navigate('/elsewhere') })
    expect(router.state.location.pathname).toBe('/metering/imports')
    expect(container.textContent).toContain('common.unsavedChanges.title')
})

describe('ImportsPage SDAT-CH deletion gating', () => {
    function historyLog(overrides: Record<string, unknown> = {}) {
        return {
            id: 'log-1',
            zev: 'zev-1',
            created_at: '2026-03-10T09:00:00Z',
            source: 'sdatch',
            filename: 'delivery.xml',
            rows_total: 96,
            rows_imported: 96,
            rows_overwritten: 0,
            rows_skipped: 0,
            ...overrides,
        }
    }

    function openBulkDelete() {
        act(() => {
            buttons('pages.imports.actions.deleteImports')[0].click()
        })
    }

    function setInputValue(input: HTMLInputElement, value: string) {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
        act(() => {
            setter.call(input, value)
            input.dispatchEvent(new Event('input', { bubbles: true }))
        })
    }

    it('gates a quarantine-replacement import like a billable overwrite', () => {
        importLogsData = [
            historyLog({
                id: 'log-held',
                filename: 'held.xml',
                rows_overwritten: 0,
                result_status: 'accepted',
                result_counts: {
                    created: 0, overwritten: 0, held: 4, promoted: 0, duplicate: 0,
                    stale: 0, excluded: 0, rejected: 0, quarantine_overwritten: 4,
                },
                deletable: false,
                deletion_protection_code: 'quarantine_replace_protected',
            }),
            historyLog({ id: 'log-clean', filename: 'clean.xml' }),
        ]
        renderPage()
        // The protected log has no deletion control; its protocol explains why.
        const rows = Array.from(container.querySelectorAll('tbody tr'))
        const heldRow = rows.find((row) => row.textContent?.includes('held.xml'))!
        const actions = Array.from(heldRow.querySelectorAll('button')).find(
            (button) => button.getAttribute('aria-label') === 'pages.imports.actions.rowActions',
        )!
        expect(actions).toBeUndefined()
        const protocol = Array.from(heldRow.querySelectorAll('button')).find(
            (button) => button.getAttribute('aria-label') === 'pages.imports.actions.openProtocol',
        )!
        act(() => protocol.click())
        expect(container.textContent).toContain('pages.imports.delete.quarantineProtected')
        act(() => {
            (container.querySelector('.form-modal-close') as HTMLButtonElement).click()
        })
        // …and a bulk selection containing it is blocked all-or-nothing.
        openBulkDelete()
        const dates = container.querySelectorAll<HTMLInputElement>('input[type=date]')
        setInputValue(dates[0], '2026-03-01')
        setInputValue(dates[1], '2026-03-31')
        expect(container.textContent).toContain('pages.imports.delete.blockedNotice')
        expect(buttons('pages.imports.delete.reviewAction')[0].disabled).toBe(true)
    })
})


describe('import deletion result feedback', () => {
    it.each([2, 3])('passes the plural count for deletion mutation %s with held readings', (index) => {
        goToStep2WithFiles('one.xml')
        startImport()
        const { scope } = mutateCalls[0].vars
        act(() => mutationOptions[index].onSuccess({
            deleted_logs: 2, deleted_readings: 4, deleted_quarantined_readings: 6,
        }, { id: 'log-1', scope }))
        expect(translate).toHaveBeenCalledWith('pages.imports.messages.deleteSuccessWithHeld', {
            count: 2, readings: 4, held: 6,
        })
    })
})

const invoiceKeys = [
    queryKeys.invoices.detail('inv-1'), queryKeys.invoices.list('zev-1'), queryKeys.invoices.mine(),
    queryKeys.invoices.periodOverview('zev-1', '2026-03-01', '2026-03-31'),
    queryKeys.invoices.readiness('zev-1'), queryKeys.invoices.readinessList('zev-1'), queryKeys.invoices.attention('zev-1'),
]

it.each([1, 2, 3])('invalidates cached invoice/readiness state after mutation %s', index => {
    goToStep2WithFiles('correction.xml')
    startImport()
    for (const key of invoiceKeys) cacheClient.setQueryData(key, { needs_data_review: false })
    if (index === 1) resolveUpload([{ file: uploadFiles()[0], value: sdatLog({ rows_imported: 0, rows_overwritten: 4 }), error: null }])
    else act(() => mutationOptions[index].onSuccess({ deleted_logs: 1, deleted_readings: 4 }, mutateCalls[0].vars))
    for (const key of invoiceKeys) expect(cacheClient.getQueryState(key)?.isInvalidated).toBe(true)
})

it.each(['correctionOnly', 'unchanged', 'accepted'] as const)('uses the structured %s outcome for the success toast', kind => {
    goToStep2WithFiles('delivery.xml')
    startImport()
    const counts = sdatLog().result_counts!
    const log = sdatLog({ rows_imported: kind === 'accepted' ? 2 : 0,
        rows_overwritten: kind === 'correctionOnly' ? 4 : 0,
        result_status: kind === 'unchanged' ? 'unchanged' : 'accepted',
        result_counts: { ...counts, created: kind === 'accepted' ? 2 : 0, overwritten: kind === 'correctionOnly' ? 4 : 0 },
        warnings: kind === 'accepted' ? [{ row: null, warning: 'An excluded block' }] : [],
    })
    resolveUpload([{ file: uploadFiles()[0], value: log, error: null }])
    expect(pushToast).toHaveBeenCalledWith(`pages.imports.messages.importSdat_${kind}`, 'success')
    expect(pushToast).not.toHaveBeenCalledWith('pages.imports.messages.importSuccessWithOverwrites', 'success')
})

it('counts new, corrected and held observations in a mixed CSV/SDAT batch', () => {
    goToStep2WithFiles('manual.csv', 'information.xml')
    startImport()
    const files = uploadFiles()
    resolveUpload([
        { file: files[0], value: sdatLog({ source: 'csv', result_status: '', rows_imported: 6, rows_overwritten: 4, result_counts: {} }), error: null },
        { file: files[1], value: sdatLog({ result_status: 'held', rows_imported: 0, result_counts: { ...sdatLog().result_counts!, created: 0, held: 3 } }), error: null },
    ])
    expect(translate).toHaveBeenCalledWith('pages.imports.messages.importBatchSuccess', {
        files: 2, imported: 2, skipped: 0, overwritten: 4, held: 3, count: 0,
    })
})
