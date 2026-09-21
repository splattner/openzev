import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ImportPreviewResult } from '../src/types/api'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const mutateCalls: Array<{ vars: any; opts?: { onSuccess?: (result: any) => void; onError?: (error: any) => void } }> = []
const mutationOptions: Array<any> = []
const pushToast = vi.fn()
const refetchLogs = vi.fn()
const translate = vi.fn((key: string) => key)

vi.mock('@tanstack/react-query', () => ({
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
    useQuery: () => ({ data: importLogsData, isLoading: false, isError: !!logsError, error: logsError, refetch: refetchLogs }),
    useMutation: (options: any) => {
        mutationOptions.push(options)
        return {
            isPending: false,
            mutate: (vars: unknown, opts?: any) => {
                mutateCalls.push({ vars, opts })
            },
        }
    },
}))

let selectedZevId = 'zev-1'
let importLogsData: any[] = []
let logsError: unknown = null
// Exercise date selection without depending on the shared calendar's DOM.
vi.mock('../src/components/CivilDateInput', () => ({
    CivilDateInput: ({ value, onChange }: { value: string; onChange: (value: string) => void }) =>
        createElement('input', { type: 'date', value, onChange: (event: React.ChangeEvent<HTMLInputElement>) => onChange(event.target.value) }),
}))
vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => ({
        selectedZevId,
        selectedZev: selectedZevId ? { id: selectedZevId, name: 'ZEV 1' } : null,
    }),
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

function buttons(label: string): HTMLButtonElement[] {
    return Array.from(container.querySelectorAll('button')).filter(
        (button) => button.textContent === label,
    ) as HTMLButtonElement[]
}

function openWizard() {
    act(() => {
        buttons('pages.imports.actions.newImport')[0].click()
    })
}

function attachFile() {
    const input = container.querySelector('input[type=file]') as HTMLInputElement
    const file = new File(['meter_id,timestamp,energy_kwh\nM1,2026-01-01T00:00:00Z,1.0'], 'readings.csv', {
        type: 'text/csv',
    })
    Object.defineProperty(input, 'files', { value: [file], configurable: true })
    act(() => {
        input.dispatchEvent(new Event('change', { bubbles: true }))
    })
}

function goToStep2() {
    openWizard()
    attachFile()
    act(() => {
        buttons('pages.imports.wizard.nextConfig')[0].click()
    })
}

function loadPreview() {
    act(() => {
        buttons('pages.imports.loadPreview')[0].click()
    })
}

function succeedPreview(preview: ImportPreviewResult) {
    act(() => {
        mutateCalls[mutateCalls.length - 1].opts?.onSuccess?.(preview)
    })
}

function startButton(): HTMLButtonElement {
    return buttons('pages.imports.wizard.startImport')[0]
}

function renderPage() {
    act(() => {
        root.render(
            createElement(MantineProvider, null,
                createElement(MemoryRouter, null, createElement(ImportsPage))),
        )
    })
}

function cleanPreview(): ImportPreviewResult {
    return {
        rows_total: 1,
        preview_rows: [
            {
                row: 2,
                meter_id: 'M1',
                metering_point_exists: true,
                meter_type: 'consumption',
                timestamp: '2026-01-01',
                energy: '1.0',
            },
        ],
        summary: { existing_metering_points: 1, missing_metering_points: 0, rows_previewed: 1, rows_skipped_existing: 0 },
        missing_meter_ids: [],
        errors: [],
    }
}

beforeEach(() => {
    mutateCalls.length = 0
    mutationOptions.length = 0
    pushToast.mockClear()
    refetchLogs.mockClear()
    selectedZevId = 'zev-1'
    importLogsData = []
    logsError = null
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
    container.remove()
})

describe('ImportsPage wizard gating', () => {
    it('allows merge re-imports when existing days will be skipped', () => {
        goToStep2()
        loadPreview()
        const preview = cleanPreview()
        preview.summary.rows_skipped_existing = 15
        succeedPreview(preview)
        expect(container.textContent).toContain('pages.imports.preview.existingRowsSkipped')
        expect(startButton().disabled).toBe(false)
        act(() => startButton().click())
        expect(mutateCalls.at(-1)?.vars.overwriteExisting).toBe(false)
    })

    it('requires a ZEV before advancing past step 1', () => {
        selectedZevId = ''
        renderPage()
        openWizard()
        attachFile()
        expect(buttons('pages.imports.wizard.nextConfig')[0].disabled).toBe(true)
        expect(container.textContent).toContain('pages.imports.messages.selectZevFirst')
    })

    it('sends zev_id with the preview request', () => {
        goToStep2()
        loadPreview()
        expect(mutateCalls).toHaveLength(1)
        expect(mutateCalls[0].vars.zevId).toBe('zev-1')
    })

    it('blocks Start Import while the preview has errors', () => {
        goToStep2()
        loadPreview()
        succeedPreview({ ...cleanPreview(), errors: [{ row: 2, error: 'Invalid numeric value' }] })
        expect(startButton().disabled).toBe(true)
        expect(mutateCalls).toHaveLength(1)
    })

    it('blocks Start Import while meters are missing and shows the overflow count', () => {
        goToStep2()
        loadPreview()
        const missing = Array.from({ length: 51 }, (_, index) => `M-${index}`)
        succeedPreview({
            ...cleanPreview(),
            preview_rows: [],
            summary: { existing_metering_points: 0, missing_metering_points: 51, rows_previewed: 0, rows_skipped_existing: 0 },
            missing_meter_ids: missing.slice(0, 50),
        })
        expect(startButton().disabled).toBe(true)
        expect(container.textContent).toContain('pages.imports.preview.andMore')
    })

    it('renders no overflow count when exactly 50 meters are missing', () => {
        goToStep2()
        loadPreview()
        const missing = Array.from({ length: 50 }, (_, index) => `M-${index}`)
        succeedPreview({
            ...cleanPreview(),
            preview_rows: [],
            summary: { existing_metering_points: 0, missing_metering_points: 50, rows_previewed: 0, rows_skipped_existing: 0 },
            missing_meter_ids: missing,
        })
        expect(container.textContent).not.toContain('pages.imports.preview.andMore')
    })

    it('invalidates the preview when the configuration changes', () => {
        goToStep2()
        loadPreview()
        succeedPreview(cleanPreview())
        expect(startButton().disabled).toBe(false)
        const headerCheckbox = container.querySelectorAll('input[type=checkbox]')[0] as HTMLInputElement
        act(() => {
            headerCheckbox.click()
        })
        expect(container.textContent).toContain('pages.imports.messages.previewOutdated')
        expect(startButton().disabled).toBe(true)
    })

    it('requires a new preview for a replacement file with identical metadata', () => {
        goToStep2()
        loadPreview()
        succeedPreview(cleanPreview())
        const original = mutateCalls[0].vars.file as File
        act(() => { buttons('pages.imports.wizard.back')[0].click() })
        const input = container.querySelector('input[type=file]') as HTMLInputElement
        const replacement = new File(['x'.repeat(original.size)], original.name, { lastModified: original.lastModified })
        Object.defineProperty(input, 'files', { value: [replacement], configurable: true })
        act(() => { input.dispatchEvent(new Event('change', { bubbles: true })) })
        act(() => { buttons('pages.imports.wizard.nextConfig')[0].click() })
        // Even a late response from the previous request must stay invalid.
        succeedPreview(cleanPreview())
        expect(startButton().disabled).toBe(true)
    })

    it('resets the wizard after a successful import', () => {
        goToStep2()
        loadPreview()
        succeedPreview(cleanPreview())
        act(() => {
            startButton().click()
        })
        expect(mutateCalls).toHaveLength(2)
        act(() => {
            mutationOptions[1].onSuccess({ rows_imported: 1, rows_skipped: 0, errors: [] })
        })
        expect(container.textContent).not.toContain('pages.imports.wizard.title')
        openWizard()
        expect(buttons('pages.imports.wizard.nextConfig')[0].disabled).toBe(true)
    })

    it('confirms before importing with overwrite enabled', () => {
        goToStep2()
        loadPreview()
        succeedPreview(cleanPreview())
        const overwriteCheckbox = container.querySelectorAll('input[type=checkbox]')[1] as HTMLInputElement
        act(() => {
            overwriteCheckbox.click()
        })
        expect(startButton().disabled).toBe(true)
        loadPreview()
        expect(mutateCalls[1].vars.overwriteExisting).toBe(true)
        succeedPreview(cleanPreview())
        act(() => {
            startButton().click()
        })
        expect(mutateCalls).toHaveLength(2)
        expect(container.textContent).toContain('pages.imports.wizard.overwriteConfirmTitle')
        const confirmButtons = buttons('pages.imports.wizard.startImport')
        act(() => {
            confirmButtons[confirmButtons.length - 1].click()
        })
        expect(mutateCalls).toHaveLength(3)
        expect(mutateCalls[2].vars.overwriteExisting).toBe(true)
        expect(mutateCalls[2].vars.zevId).toBe('zev-1')
    })

    it('shows a file summary and removes the file', () => {
        openWizard()
        attachFile()
        expect(container.textContent).toContain('readings.csv')
        expect(container.textContent).toContain('pages.imports.wizard.supportedExtensions')
        act(() => {
            buttons('pages.imports.wizard.removeFile')[0].click()
        })
        expect(buttons('pages.imports.wizard.nextConfig')[0].disabled).toBe(true)
    })

    it('rejects legacy .xls files upfront', () => {
        openWizard()
        const input = container.querySelector('input[type=file]') as HTMLInputElement
        const file = new File(['x'], 'old.xls', { type: 'application/vnd.ms-excel' })
        Object.defineProperty(input, 'files', { value: [file], configurable: true })
        act(() => {
            input.dispatchEvent(new Event('change', { bubbles: true }))
        })
        expect(pushToast).toHaveBeenCalledWith('pages.imports.wizard.xlsRejected', 'error')
        expect(buttons('pages.imports.wizard.nextConfig')[0].disabled).toBe(true)
    })

    it('blocks preview on invalid numeric config', () => {
        goToStep2()
        const valuesInput = container.querySelectorAll('input[type=number]')[0] as HTMLInputElement
        setInputValue(valuesInput, '5000')
        expect(container.textContent).toContain('pages.imports.wizard.valuesCountInvalid')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(true)
        setInputValue(valuesInput, '')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(true)
        setInputValue(valuesInput, '96')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(false)
    })

    it('blocks preview on year-less timestamp formats like the backend', () => {
        goToStep2()
        const formatInput = container.querySelector('input[placeholder="%d.%m.%Y"]') as HTMLInputElement
        setInputValue(formatInput, '%d.%m')
        expect(container.textContent).toContain('pages.imports.wizard.timestampFormatInvalid')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(true)
        setInputValue(formatInput, '%d.%m.%Y')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(false)
    })

    it('blocks preview on multi-character delimiters and bare timestamp formats', () => {
        goToStep2()
        const delimiterInput = container.querySelector('input[placeholder=","]') as HTMLInputElement
        setInputValue(delimiterInput, ';;')
        expect(container.textContent).toContain('pages.imports.wizard.delimiterInvalid')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(true)
        setInputValue(delimiterInput, ',')
        const formatInput = container.querySelector('input[placeholder="%d.%m.%Y"]') as HTMLInputElement
        setInputValue(formatInput, 'garbage')
        expect(container.textContent).toContain('pages.imports.wizard.timestampFormatInvalid')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(true)
    })

    it('opens the protocol automatically when the import has errors', () => {
        goToStep2()
        loadPreview()
        succeedPreview(cleanPreview())
        act(() => {
            startButton().click()
        })
        act(() => {
            mutationOptions[1].onSuccess({
                id: 'log-1',
                batch_id: 'batch-1',
                rows_imported: 1,
                rows_skipped: 1,
                errors: [{ row: 2, error: 'Duplicate reading' }],
            })
        })
        expect(container.textContent).not.toContain('pages.imports.wizard.title')
        expect(container.textContent).toContain('pages.imports.protocol.title')
        expect(pushToast).toHaveBeenCalledWith(
            'pages.imports.messages.importSuccessWithIssues',
            expect.objectContaining({}),
        )
    })

    it('treats overwrite warnings as success, not issues', () => {
        goToStep2()
        loadPreview()
        succeedPreview(cleanPreview())
        act(() => {
            startButton().click()
        })
        act(() => {
            mutationOptions[1].onSuccess({
                id: 'log-1',
                batch_id: 'batch-1',
                rows_imported: 2,
                rows_overwritten: 1,
                rows_skipped: 0,
                errors: [],
                warnings: [{ row: null, warning: 'Existing readings were updated.' }],
            })
        })
        expect(pushToast).toHaveBeenCalledWith(
            'pages.imports.messages.importSuccessWithOverwrites',
            'success',
        )
        expect(translate).toHaveBeenCalledWith('pages.imports.messages.importSuccessWithOverwrites', {
            imported: 2, skipped: 0, overwritten: 1,
        })
    })

    it('accepts tab delimiter escape and day-of-year timestamp format', () => {
        goToStep2()
        const delimiterInput = container.querySelector('input[placeholder=","]') as HTMLInputElement
        setInputValue(delimiterInput, '\\t')
        expect(container.textContent).not.toContain('pages.imports.wizard.delimiterInvalid')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(false)
        const formatInput = container.querySelector('input[placeholder="%d.%m.%Y"]') as HTMLInputElement
        setInputValue(formatInput, '%Y-%j')
        expect(container.textContent).not.toContain('pages.imports.wizard.timestampFormatInvalid')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(false)
    })

    it('copies missing meter IDs', () => {
        const writeText = vi.fn().mockResolvedValue(undefined)
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
        goToStep2()
        loadPreview()
        succeedPreview({
            ...cleanPreview(),
            preview_rows: [],
            summary: { existing_metering_points: 0, missing_metering_points: 1, rows_previewed: 0, rows_skipped_existing: 0 },
            missing_meter_ids: ['M-9'],
        })
        act(() => {
            buttons('pages.imports.preview.copyMissingIds')[0].click()
        })
        expect(writeText).toHaveBeenCalledWith('M-9')
    })

    it('bulk delete uses an armed confirmation state inside one modal', () => {
        importLogsData = [
            {
                id: 'log-1',
                zev: 'zev-1',
                created_at: '2026-03-10T09:00:00Z',
                source: 'csv',
                filename: 'f.csv',
                rows_total: 1,
                rows_imported: 1,
                rows_skipped: 0,
            },
        ]
        renderPage()
        act(() => {
            buttons('pages.imports.actions.deleteImports')[0].click()
        })
        expect(container.textContent).toContain('pages.imports.delete.visibleImpact')
        const dateInputs = container.querySelectorAll('input[type=date]')
        setInputValue(dateInputs[0] as HTMLInputElement, '2026-03-01')
        setInputValue(dateInputs[1] as HTMLInputElement, '2026-03-31')
        act(() => {
            buttons('pages.imports.delete.reviewAction')[0].click()
        })
        expect(container.textContent).toContain('pages.imports.delete.bulkPeriodMessage')
        act(() => {
            buttons('pages.imports.wizard.back')[0].click()
        })
        expect(container.textContent).toContain('pages.imports.delete.modeLabel')
        act(() => {
            buttons('pages.imports.delete.reviewAction')[0].click()
        })
        act(() => {
            buttons('pages.imports.delete.confirmAction')[0].click()
        })
        expect(mutateCalls).toHaveLength(1)
        expect(mutateCalls[0].vars).toEqual({
            mode: 'period',
            dateFrom: '2026-03-01',
            dateTo: '2026-03-31',
            zevId: 'zev-1',
        })
    })

    it('bulk delete copy covers all visible ZEVs without a selection', () => {
        selectedZevId = ''
        importLogsData = [
            {
                id: 'log-1',
                zev: 'zev-9',
                created_at: '2026-03-10T09:00:00Z',
                source: 'csv',
                filename: 'f.csv',
                rows_total: 1,
                rows_imported: 1,
                rows_skipped: 0,
            },
        ]
        renderPage()
        act(() => {
            buttons('pages.imports.actions.deleteImports')[0].click()
        })
        expect(container.textContent).toContain('pages.imports.delete.bulkDescriptionAll')
        expect(container.textContent ?? '').not.toMatch(/bulkDescription(?!All)/)
    })

    it('shows load-error details with a retry action', () => {
        logsError = { response: { data: { detail: 'Database unavailable' } } }
        renderPage()
        expect(container.textContent).toContain('pages.imports.loadFailed')
        expect(container.textContent).toContain('Database unavailable')
        act(() => {
            buttons('common.retry')[0].click()
        })
        expect(refetchLogs).toHaveBeenCalled()
    })

    it('disables deletion and explains protection for overwritten imports', () => {
        twoLogs()
        importLogsData[0].rows_overwritten = 1
        renderPage()
        const row = Array.from(container.querySelectorAll('tbody tr')).find((entry) => entry.textContent?.includes('alpha.csv'))!
        const actions = Array.from(row.querySelectorAll('button')).find((button) => button.textContent === 'pages.imports.actions.rowActions')!
        expect(actions.disabled).toBe(true)
        const protocol = Array.from(row.querySelectorAll('button')).find((button) => button.textContent === 'pages.imports.actions.openProtocol')!
        act(() => protocol.click())
        expect(container.textContent).toContain('pages.imports.delete.overwriteProtected')
    })

    it('explains server rejection of single and bulk overwrite deletion', () => {
        for (const mutation of [mutationOptions[2], mutationOptions[3]]) {
            act(() => mutation.onError({ response: { data: { code: 'overwrite_import_protected' } } }))
            expect(pushToast).toHaveBeenLastCalledWith('pages.imports.delete.overwriteProtected', 'error')
        }
    })

    it('filters history by filename and source', () => {
        twoLogs()
        const search = container.querySelector('input[type=search]') as HTMLInputElement
        setInputValue(search, 'alpha')
        expect(container.textContent).toContain('alpha.csv')
        expect(container.textContent).not.toContain('beta.xml')
        setInputValue(search, '')
        const select = container.querySelector('.imports-history-filters select') as HTMLSelectElement
        const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
        act(() => {
            setter.call(select, 'sdatch')
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        expect(container.textContent).not.toContain('alpha.csv')
        expect(container.textContent).toContain('beta.xml')
    })

    it('sorts history by raw values', () => {
        twoLogs()
        const headerButton = Array.from(container.querySelectorAll('th button')).find(
            (button) => button.getAttribute('aria-label') === 'pages.imports.columns.created',
        ) as HTMLButtonElement
        expect(container.textContent.indexOf('beta.xml')).toBeLessThan(
            container.textContent.indexOf('alpha.csv'),
        )
        act(() => {
            headerButton.click()
        })
        expect(container.textContent.indexOf('alpha.csv')).toBeLessThan(
            container.textContent.indexOf('beta.xml'),
        )
    })

    it('renders the protocol errors in a table', () => {
        goToStep2()
        loadPreview()
        succeedPreview(cleanPreview())
        act(() => {
            startButton().click()
        })
        act(() => {
            mutationOptions[1].onSuccess({
                id: 'log-1',
                batch_id: 'batch-1',
                rows_imported: 1,
                rows_skipped: 1,
                errors: [{ row: 2, meter_id: 'M-9', error: 'Duplicate reading' }],
            })
        })
        expect(container.textContent).toContain('M-9')
        expect(container.textContent).toContain('Duplicate reading')
    })

    it('maps 413 and 429 upload failures to localized messages', () => {
        goToStep2()
        loadPreview()
        act(() => {
            mutateCalls[mutateCalls.length - 1].opts?.onError?.({ response: { status: 413, data: {} } })
        })
        expect(pushToast).toHaveBeenCalledWith('pages.imports.messages.importTooLarge', expect.objectContaining({}))
        act(() => {
            mutationOptions[1].onError({ response: { status: 429, data: { detail: 'throttled' } } })
        })
        expect(pushToast).toHaveBeenCalledWith('pages.imports.messages.importThrottled', 'error')
    })

    it('renders a row action menu per log', () => {
        twoLogs()
        expect(buttons('pages.imports.actions.rowActions')).toHaveLength(2)
        expect(buttons('pages.imports.actions.openProtocol')).toHaveLength(2)
    })
})

function setInputValue(input: HTMLInputElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    act(() => {
        setter.call(input, value)
        input.dispatchEvent(new Event('input', { bubbles: true }))
    })
}

function twoLogs() {
    importLogsData = [
        {
            id: 'log-1',
            zev: 'zev-1',
            created_at: '2026-03-10T09:00:00Z',
            source: 'csv',
            filename: 'alpha.csv',
            rows_total: 10,
            rows_imported: 9,
            rows_skipped: 1,
        },
        {
            id: 'log-2',
            zev: 'zev-1',
            created_at: '2026-03-11T09:00:00Z',
            source: 'sdatch',
            filename: 'beta.xml',
            rows_total: 4,
            rows_imported: 4,
            rows_skipped: 0,
        },
    ]
    renderPage()
}
