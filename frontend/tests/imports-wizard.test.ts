import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ImportPreviewResult } from '../src/types/api'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const mutateCalls: Array<{ vars: any; opts?: { onSuccess?: (result: any) => void; onError?: (error: any) => void } }> = []
const mutationOptions: Array<any> = []
// Settings detection goes through its own mutation; tracking it separately
// keeps the preview/upload call indexes the rest of this file relies on.
const detectCalls: Array<{ vars: unknown }> = []
// null = detection fails at once (defaults stay); 'pending' = never answers.
let detectResult: unknown | 'pending' | null = null
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
                if (options.mutationFn?.name === 'detectCsvSettings') {
                    detectCalls.push({ vars })
                    if (detectResult === 'pending') return
                    if (detectResult === null) opts?.onError?.(new Error('detect failed'))
                    else opts?.onSuccess?.(detectResult)
                    return
                }
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
        const { files } = mutateCalls[mutateCalls.length - 1].vars as { files: File[] }
        mutateCalls[mutateCalls.length - 1].opts?.onSuccess?.(files.map((file) => ({ file, value: preview, error: null })))
    })
}

/** Resolve the most recent upload mutation as if every file imported. */
function succeedUpload(...logs: Array<Record<string, unknown>>) {
    const { files } = mutateCalls[mutateCalls.length - 1].vars as { files: File[] }
    act(() => {
        mutationOptions[1].onSuccess(files.map((file, index) => ({ file, value: logs[index] ?? logs[0], error: null })))
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
    detectCalls.length = 0
    detectResult = null
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
        const original = (mutateCalls[0].vars.files as File[])[0]
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
        succeedUpload({ rows_imported: 1, rows_skipped: 0, errors: [] })
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
        succeedUpload({
                id: 'log-1',
                batch_id: 'batch-1',
                rows_imported: 1,
                rows_skipped: 1,
                errors: [{ row: 2, error: 'Duplicate reading' }],
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
        succeedUpload({
                id: 'log-1',
                batch_id: 'batch-1',
                rows_imported: 2,
                rows_overwritten: 1,
                rows_skipped: 0,
                errors: [],
                warnings: [{ row: null, warning: 'Existing readings were updated.' }],
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
        succeedUpload({
                id: 'log-1',
                batch_id: 'batch-1',
                rows_imported: 1,
                rows_skipped: 1,
                errors: [{ row: 2, meter_id: 'M-9', error: 'Duplicate reading' }],
            })
        expect(container.textContent).toContain('M-9')
        expect(container.textContent).toContain('Duplicate reading')
    })

    it('maps 413 and 429 upload failures to localized messages', () => {
        goToStep2()
        loadPreview()
        act(() => {
            const { files } = mutateCalls[mutateCalls.length - 1].vars as { files: File[] }
            mutateCalls[mutateCalls.length - 1].opts?.onSuccess?.([
                { file: files[0], value: null, error: { response: { status: 413, data: {} } } },
            ])
        })
        expect(container.textContent).toContain('pages.imports.messages.importTooLarge')
        succeedPreview(cleanPreview())
        act(() => startButton().click())
        const { files } = mutateCalls[mutateCalls.length - 1].vars as { files: File[] }
        act(() => {
            mutationOptions[1].onSuccess([
                { file: files[0], value: null, error: { response: { status: 429, data: { detail: 'throttled' } } } },
            ])
        })
        expect(pushToast).toHaveBeenCalledWith('pages.imports.messages.importThrottled', 'error')
        // A failed import keeps the wizard open for a retry.
        expect(container.textContent).toContain('pages.imports.wizard.title')
    })

    it('renders a row action menu per log', () => {
        twoLogs()
        expect(buttons('pages.imports.actions.rowActions')).toHaveLength(2)
        expect(buttons('pages.imports.actions.openProtocol')).toHaveLength(2)
    })

    it('offers the direction column for both row formats', () => {
        // VNB profile exports carry the consumption/feed-in discriminator as
        // an OBIS code column, so the daily profile needs the mapping too.
        goToStep2()
        expect(labelTexts()).toContain('pages.imports.wizard.directionCol')
        selectRowFormat('daily_15min')
        expect(labelTexts()).toContain('pages.imports.wizard.directionCol')
        expect(container.textContent).toContain('pages.imports.wizard.directionColHint')
    })

    it('leaves the direction column empty without a value-like placeholder', () => {
        // The other column fields carry real defaults, so a greyed-out sample
        // in this one reads as already configured — and an unset direction
        // column silently falls back to meter-type inference.
        goToStep2()
        selectRowFormat('daily_15min')
        const input = directionInput()
        expect(input.value).toBe('')
        expect(input.placeholder).toBe('')
    })

    it('shows the direction a previewed row would import', () => {
        goToStep2()
        loadPreview()
        const preview = cleanPreview()
        preview.preview_rows[0].directions = ['out']
        succeedPreview(preview)
        expect(container.textContent).toContain('pages.imports.preview.directionOut')
        expect(container.textContent).not.toContain('pages.imports.preview.directionIn')
    })

    it('lists both directions when a row splits by sign', () => {
        goToStep2()
        loadPreview()
        const preview = cleanPreview()
        preview.preview_rows[0].directions = ['in', 'out']
        succeedPreview(preview)
        expect(container.textContent).toContain('pages.imports.preview.directionIn')
        expect(container.textContent).toContain('pages.imports.preview.directionOut')
    })
})

/** The wizard's direction-column input, found via its label. */
function directionInput(): HTMLInputElement {
    const label = Array.from(container.querySelectorAll('label')).find(
        (candidate) =>
            candidate.querySelector('span')?.textContent === 'pages.imports.wizard.directionCol',
    )!
    return label.querySelector('input') as HTMLInputElement
}

/** Labels rendered inside the open wizard, by their translation key. */
function labelTexts(): string[] {
    return Array.from(container.querySelectorAll('label > span')).map(
        (span) => span.textContent ?? '',
    )
}

function selectRowFormat(profile: string) {
    const select = Array.from(container.querySelectorAll('select')).find((candidate) =>
        Array.from(candidate.options).some((option) => option.value === profile),
    ) as HTMLSelectElement
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
    act(() => {
        setter.call(select, profile)
        select.dispatchEvent(new Event('change', { bubbles: true }))
    })
}

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

describe('ImportsPage multi-file import', () => {
    function pick(...names: string[]) {
        const input = container.querySelector('input[type=file]') as HTMLInputElement
        const picked = names.map((name, index) => new File([`meter_id,timestamp,energy_kwh\nM${index},2026-01-01T00:00:00Z,1.0`], name, { type: 'text/csv' }))
        Object.defineProperty(input, 'files', { value: picked, configurable: true })
        act(() => {
            input.dispatchEvent(new Event('change', { bubbles: true }))
        })
    }

    function goToStep2WithFiles(...names: string[]) {
        openWizard()
        pick(...names)
        act(() => {
            buttons('pages.imports.wizard.nextConfig')[0].click()
        })
    }

    it('accepts several files, lists each and removes them one at a time', () => {
        openWizard()
        expect((container.querySelector('input[type=file]') as HTMLInputElement).multiple).toBe(true)
        pick('a.csv', 'b.csv', 'c.csv')
        expect(buttons('pages.imports.wizard.removeFile')).toHaveLength(3)
        expect(container.textContent).toContain('pages.imports.wizard.sameSettingsHint')
        act(() => {
            buttons('pages.imports.wizard.removeFile')[1].click()
        })
        expect(container.textContent).toContain('a.csv')
        expect(container.textContent).not.toContain('b.csv')
        expect(container.textContent).toContain('c.csv')
        expect(buttons('pages.imports.wizard.nextConfig')[0].disabled).toBe(false)
    })

    it('previews and uploads every file with the same settings', () => {
        goToStep2WithFiles('a.csv', 'b.csv')
        loadPreview()
        expect((mutateCalls[0].vars.files as File[]).map((file) => file.name)).toEqual(['a.csv', 'b.csv'])
        succeedPreview(cleanPreview())
        expect(container.textContent).toContain('a.csv')
        expect(container.textContent).toContain('b.csv')
        act(() => startButton().click())
        expect((mutateCalls[1].vars.files as File[]).map((file) => file.name)).toEqual(['a.csv', 'b.csv'])
        succeedUpload({ id: 'l', rows_imported: 3, rows_skipped: 1, errors: [] })
        expect(pushToast).toHaveBeenCalledWith(
            'pages.imports.messages.importBatchSuccess',
            'success',
        )
        expect(container.textContent).not.toContain('pages.imports.wizard.title')
    })

    it('blocks the import while any file has preview errors', () => {
        goToStep2WithFiles('a.csv', 'b.csv')
        loadPreview()
        act(() => {
            const { files } = mutateCalls[0].vars as { files: File[] }
            mutateCalls[0].opts?.onSuccess?.([
                { file: files[0], value: cleanPreview(), error: null },
                { file: files[1], value: { ...cleanPreview(), errors: [{ row: 2, error: 'Bad value' }] }, error: null },
            ])
        })
        expect(startButton().disabled).toBe(true)
        expect(container.textContent).toContain('Bad value')
    })

    it('counts a meter missing from several files once', () => {
        goToStep2WithFiles('a.csv', 'b.csv')
        loadPreview()
        const missing = {
            ...cleanPreview(),
            summary: { existing_metering_points: 0, missing_metering_points: 1, rows_previewed: 1, rows_skipped_existing: 0 },
            missing_meter_ids: ['M-1'],
        }
        succeedPreview(missing)
        expect(container.textContent).toContain('pages.imports.previewMissingBanner')
        expect(container.textContent).not.toContain('pages.imports.preview.andMore')
        expect(translate).toHaveBeenCalledWith('pages.imports.previewMissingBanner', { count: 1 })
    })

    it('keeps only the failed files selected after a partial import', () => {
        goToStep2WithFiles('a.csv', 'b.csv', 'c.csv')
        loadPreview()
        succeedPreview(cleanPreview())
        act(() => startButton().click())
        const { files } = mutateCalls[1].vars as { files: File[] }
        act(() => {
            mutationOptions[1].onSuccess([
                { file: files[0], value: { id: 'l1', rows_imported: 1, rows_skipped: 0, errors: [] }, error: null },
                { file: files[1], value: null, error: { response: { status: 400, data: { error: 'Boom' } } } },
                { file: files[2], value: { id: 'l3', rows_imported: 1, rows_skipped: 0, errors: [] }, error: null },
            ])
        })
        expect(pushToast).toHaveBeenCalledWith(
            'pages.imports.messages.importBatchPartial',
            'error',
        )
        expect(translate).toHaveBeenCalledWith('pages.imports.messages.importBatchPartial', {
            done: 2,
            total: 3,
            failed: 1,
            names: 'b.csv',
        })
        expect(container.textContent).toContain('pages.imports.wizard.title')
        // The retry covers only the failed file and its preview is still valid.
        expect(startButton().disabled).toBe(false)
        act(() => startButton().click())
        expect((mutateCalls[2].vars.files as File[]).map((file) => file.name)).toEqual(['b.csv'])
    })
})

describe('ImportsPage settings detection', () => {
    function detected(overrides: Record<string, unknown> = {}, undetected: string[] = []) {
        return {
            detected: true,
            undetected,
            settings: {
                has_header: false,
                delimiter: ';',
                format_profile: 'standard',
                timestamp_format: '%d.%m.%Y %H:%M',
                interval_minutes: 15,
                values_count: 96,
                column_map: { meter_id: '0', timestamp: '1', energy_kwh: '2', direction: null, energy_start: null },
                ...overrides,
            },
        }
    }

    function input(placeholder: string): HTMLInputElement {
        return container.querySelector(`input[placeholder="${placeholder}"]`) as HTMLInputElement
    }

    function pickAndNext(...names: string[]) {
        openWizard()
        const field = container.querySelector('input[type=file]') as HTMLInputElement
        const picked = names.map((name) => new File(['x'], name, { type: 'text/csv' }))
        Object.defineProperty(field, 'files', { value: picked, configurable: true })
        act(() => { field.dispatchEvent(new Event('change', { bubbles: true })) })
        act(() => { buttons('pages.imports.wizard.nextConfig')[0].click() })
    }

    it('applies the detected settings and sends them with the preview', () => {
        detectResult = detected()
        pickAndNext('readings.csv')
        expect(detectCalls).toHaveLength(1)
        expect((detectCalls[0].vars as File).name).toBe('readings.csv')
        expect(container.textContent).toContain('pages.imports.detection.done')
        expect((container.querySelector('input[type=checkbox]') as HTMLInputElement).checked).toBe(false)
        expect(input(',').value).toBe(';')
        loadPreview()
        expect(mutateCalls[0].vars).toMatchObject({
            hasHeader: false,
            delimiter: ';',
            formatProfile: 'standard',
            timestampFormat: '%d.%m.%Y %H:%M',
            columnMap: { meter_id: '0', timestamp: '1', energy_kwh: '2', direction: '', energy_start: '' },
        })
    })

    it('applies a daily-profile detection with interval settings', () => {
        detectResult = detected({
            has_header: true,
            delimiter: ',',
            format_profile: 'daily_15min',
            timestamp_format: '',
            interval_minutes: 60,
            values_count: 24,
            column_map: { meter_id: 'Zählpunkt', timestamp: 'Datum', energy_kwh: null, direction: 'Richtung', energy_start: '00:00' },
        })
        pickAndNext('daily.csv')
        loadPreview()
        expect(mutateCalls[0].vars).toMatchObject({
            formatProfile: 'daily_15min',
            timestampFormat: '',
            intervalMinutes: 60,
            valuesCount: 24,
            columnMap: { meter_id: 'Zählpunkt', timestamp: 'Datum', energy_kwh: '', direction: 'Richtung', energy_start: '00:00' },
        })
    })

    it('shows the tab delimiter in the escape form the field accepts', () => {
        detectResult = detected({ delimiter: '\t' })
        pickAndNext('tabbed.csv')
        expect(input(',').value).toBe('\\t')
        expect(container.textContent).not.toContain('pages.imports.wizard.delimiterInvalid')
    })

    it('names what could not be detected and keeps defaults for it', () => {
        detectResult = detected({ column_map: { meter_id: null, timestamp: '1', energy_kwh: '2', direction: null, energy_start: null } }, ['meter_id'])
        pickAndNext('readings.csv')
        expect(translate).toHaveBeenCalledWith('pages.imports.detection.undetected', { fields: 'pages.imports.wizard.meterIdCol' })
        loadPreview()
        // Headerless standard default for the field that stayed undetected.
        expect((mutateCalls[0].vars as any).columnMap.meter_id).toBe('0')
    })

    it('keeps the defaults and says so when detection does not recognise the file', () => {
        detectResult = { ...detected(), detected: false, undetected: ['file'] }
        pickAndNext('odd.csv')
        expect(input(',').value).toBe(',')
        expect(translate).toHaveBeenCalledWith('pages.imports.detection.undetected', { fields: 'pages.imports.detection.fieldFile' })
    })

    it('keeps the defaults and says so when the detection request fails', () => {
        pickAndNext('readings.csv')
        expect(container.textContent).toContain('pages.imports.detection.failed')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(false)
    })

    it('blocks the preview while detection is running', () => {
        detectResult = 'pending'
        pickAndNext('readings.csv')
        expect(container.textContent).toContain('pages.imports.detection.loading')
        expect(buttons('pages.imports.loadPreview')[0].disabled).toBe(true)
    })

    it('does not overwrite manual edits when moving back and forth, but detects again for new files', () => {
        detectResult = detected()
        pickAndNext('a.csv')
        setInputValue(input(','), '|')
        act(() => { buttons('pages.imports.wizard.back')[0].click() })
        act(() => { buttons('pages.imports.wizard.nextConfig')[0].click() })
        expect(detectCalls).toHaveLength(1)
        expect(container.querySelector('input[value="|"]')).not.toBeNull()

        act(() => { buttons('pages.imports.wizard.back')[0].click() })
        const field = container.querySelector('input[type=file]') as HTMLInputElement
        Object.defineProperty(field, 'files', { value: [new File(['x'], 'b.csv')], configurable: true })
        act(() => { field.dispatchEvent(new Event('change', { bubbles: true })) })
        act(() => { buttons('pages.imports.wizard.nextConfig')[0].click() })
        expect(detectCalls).toHaveLength(2)
        expect(container.querySelector('input[value=";"]')).not.toBeNull()
    })

    it('detects again on request, restoring the detected settings', () => {
        detectResult = detected()
        pickAndNext('a.csv')
        setInputValue(input(','), '|')
        act(() => { buttons('pages.imports.detection.redetect')[0].click() })
        expect(detectCalls).toHaveLength(2)
        expect(container.querySelector('input[value=";"]')).not.toBeNull()
    })

    it('detects from the first file and says it applies to all of them', () => {
        detectResult = detected()
        pickAndNext('a.csv', 'b.csv')
        expect(detectCalls).toHaveLength(1)
        expect((detectCalls[0].vars as File).name).toBe('a.csv')
        expect(translate).toHaveBeenCalledWith('pages.imports.detection.doneMulti', { filename: 'a.csv', count: 2 })
    })

    it('skips detection for SDAT-CH', () => {
        detectResult = detected()
        openWizard()
        const select = container.querySelector('select') as HTMLSelectElement
        act(() => {
            select.value = 'sdatch'
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        const field = container.querySelector('input[type=file]') as HTMLInputElement
        Object.defineProperty(field, 'files', { value: [new File(['<x/>'], 'a.xml')], configurable: true })
        act(() => { field.dispatchEvent(new Event('change', { bubbles: true })) })
        act(() => { buttons('pages.imports.wizard.nextConfig')[0].click() })
        expect(detectCalls).toHaveLength(0)
    })
})
