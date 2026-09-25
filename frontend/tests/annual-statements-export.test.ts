import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter } from 'react-router-dom'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k }),
}))

const mockAuth = vi.fn()
const mockManagedZev = vi.fn()

vi.mock('../src/lib/auth', () => ({
    useAuth: () => mockAuth(),
}))

vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => mockManagedZev(),
}))

vi.mock('../src/lib/api/invoices', () => ({
    downloadAnnualStatement: vi.fn(() => Promise.resolve(new Blob())),
    downloadFinancialSummary: vi.fn(() => Promise.resolve(new Blob())),
}))

vi.mock('../src/lib/api/exports', () => ({
    createAnnualStatementsExport: vi.fn(),
    fetchAnnualStatementExports: vi.fn(() => Promise.resolve([])),
    fetchExportJob: vi.fn(),
    downloadAnnualStatementsExport: vi.fn(() => Promise.resolve(new Blob())),
}))

vi.mock('../src/lib/downloadBlob', () => ({
    downloadBlob: vi.fn(),
}))

import { BillingStatementsPage } from '../src/pages/BillingStatementsPage'
import { AnnualStatementsExportCard } from '../src/features/reports/AnnualStatementsExportCard'
import * as exportsApi from '../src/lib/api/exports'
import * as invoicesApi from '../src/lib/api/invoices'
import { downloadBlob } from '../src/lib/downloadBlob'
import type { ExportJob } from '../src/types/api'
import { flush } from './pdf-test-utils'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function makeCompletedJob(overrides: Record<string, unknown> = {}) {
    return {
        id: 'job-1',
        export_type: 'annual_statements',
        zev_id: 'zev-1',
        params: { year: new Date().getFullYear() - 1 },
        status: 'completed',
        created_at: '2026-01-01T00:00:00Z',
        started_at: '2026-01-01T00:00:00Z',
        completed_at: '2026-01-01T00:00:01Z',
        file_expires_at: '2026-01-02T00:00:00Z',
        generated_count: 2,
        omitted_count: 0,
        omitted_participant_ids: [],
        error_message: '',
        expired: false,
        ...overrides,
    }
}

function renderReportsPage(component = BillingStatementsPage) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient()
    const root = createRoot(container)
    const render = (target = component) => createElement(
        MemoryRouter,
        null,
        createElement(
            MantineProvider,
            null,
            createElement(QueryClientProvider, { client }, createElement(target)),
        ),
    )
    act(() => {
        root.render(render())
    })
    return {
        container,
        rerender: (target = component) => act(() => root.render(render(target))),
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

function mockOwner({ selectedZevId, selectedZev, managedZevs }: {
    selectedZevId: string | null
    selectedZev?: { id: string; name: string } | null
    managedZevs: Array<{ id: string; name?: string }>
}) {
    mockAuth.mockReturnValue({ user: { id: 1, role: 'admin' } })
    mockManagedZev.mockReturnValue({ selectedZevId, selectedZev, managedZevs, isLoading: false })
}

async function changeYear(select: HTMLSelectElement, value: string) {
    await act(async () => {
        select.value = value
        select.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await flush()
}

async function click(button: HTMLButtonElement) {
    await act(async () => {
        button.click()
    })
    await flush()
}

function findButton(container: HTMLElement, text: string): HTMLButtonElement | undefined {
    return (Array.from(container.querySelectorAll('button')) as HTMLButtonElement[]).find(
        (button) => button.textContent === text,
    )
}

describe('BillingStatementsPage restored export', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
    })

    it('a completed export is restored and downloaded', async () => {
        mockOwner({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }],
        })
        const year = new Date().getFullYear() - 1
        const job = makeCompletedJob({ id: 'job-42', params: { year } })
        vi.mocked(exportsApi.fetchAnnualStatementExports).mockResolvedValue([job])

        const { container, unmount } = renderReportsPage(BillingStatementsPage)
        await flush()
        await flush()

        const downloadButton = findButton(container, 'pages.reports.annualStatement.downloadAll')!
        expect(downloadButton).toBeTruthy()
        await click(downloadButton)
        expect(exportsApi.downloadAnnualStatementsExport).toHaveBeenCalledWith('job-42')
        expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), `annual-statements-${year}.zip`)
        unmount()
    })
})

describe('BillingStatementsPage', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
    })

    it('prepares an export for the selected year and ZEV', async () => {
        mockOwner({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }],
        })
        const targetYear = new Date().getFullYear() - 2
        // An implementation-less mock resolves undefined, which the card would store as its job and crash on.
        vi.mocked(exportsApi.createAnnualStatementsExport).mockResolvedValue(
            makeCompletedJob({ id: 'job-new', params: { year: targetYear } }),
        )
        const { container, unmount } = renderReportsPage(BillingStatementsPage)
        await flush()
        const select = container.querySelector('select') as HTMLSelectElement
        await changeYear(select, String(targetYear))

        const prepareButton = findButton(container, 'pages.reports.annualStatement.prepare')!
        expect(prepareButton).toBeTruthy()
        await click(prepareButton)

        expect(exportsApi.createAnnualStatementsExport).toHaveBeenCalledWith({
            zev_id: 'zev-1',
            year: targetYear,
        })
        expect(invoicesApi.downloadAnnualStatement).not.toHaveBeenCalled()
        unmount()
    })

    it('cannot prepare for a stale ZEV selection', async () => {
        mockOwner({ selectedZevId: 'stale', selectedZev: null, managedZevs: [{ id: 'zev-1' }] })
        const { container, unmount } = renderReportsPage(BillingStatementsPage)
        await flush()
        expect(container.textContent).toContain('pages.reports.selectZevTitle')
        expect(container.querySelector('button')).toBeNull()
        unmount()
    })

    it('shows the empty state without a ZEV', async () => {
        mockOwner({ selectedZevId: null, selectedZev: null, managedZevs: [] })
        const { container, unmount } = renderReportsPage(BillingStatementsPage)
        await flush()
        expect(container.textContent).toContain('pages.reports.noZevTitle')
        expect(container.textContent).not.toContain('pages.reports.annualStatement.prepare')
        unmount()
    })
})

describe('AnnualStatementsExportCard polling', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
    })

    function renderCard(zevId: string, year: number) {
        const container = document.createElement('div')
        document.body.appendChild(container)
        const client = new QueryClient()
        const root = createRoot(container)
        act(() => {
            root.render(
                createElement(
                    QueryClientProvider,
                    { client },
                    createElement(AnnualStatementsExportCard, { zevId, year, enabled: true }),
                ),
            )
        })
        return {
            container,
            unmount: () => {
                act(() => root.unmount())
                container.remove()
            },
        }
    }

    function runningJob(year: number) {
        return makeCompletedJob({
            id: 'job-poll',
            params: { year },
            status: 'queued',
            started_at: null,
            completed_at: null,
            file_expires_at: null,
            generated_count: null,
            omitted_count: null,
        })
    }

    // The card polls on a 2.5 s interval; wait in small real-time steps so a
    // slow CI runner cannot flake the assertions.
    async function waitFor(predicate: () => boolean, what: string, timeoutMs: number) {
        const deadline = Date.now() + timeoutMs
        while (Date.now() < deadline) {
            if (predicate()) return
            await act(async () => {
                await new Promise((resolve) => setTimeout(resolve, 100))
            })
        }
        throw new Error(`Timed out waiting for: ${what}`)
    }

    it('a single transient poll failure does not fail a still-running job', async () => {
        const year = new Date().getFullYear() - 1
        const running = runningJob(year)
        vi.mocked(exportsApi.fetchAnnualStatementExports).mockResolvedValue([running])
        const fetchJob = vi.mocked(exportsApi.fetchExportJob)
        fetchJob.mockRejectedValueOnce(new Error('transient blip'))
        fetchJob.mockResolvedValue({ ...running, status: 'running' })

        const { container, unmount } = renderCard('zev-1', year)
        try {
            await flush()
            await flush()

            // First tick fails, second tick succeeds (≈2 × 2.5 s of polling).
            await waitFor(() => fetchJob.mock.calls.length >= 2, 'two poll attempts', 8000)
            await act(async () => {
                await new Promise((resolve) => setTimeout(resolve, 300))
            })

            expect(container.textContent).not.toContain('pages.reports.annualStatement.error')
            expect(container.textContent).toContain('pages.reports.annualStatement.preparing')
        } finally {
            unmount()
        }
    }, 15000)

    it('only repeated poll failures mark the job failed', async () => {
        const year = new Date().getFullYear() - 1
        const running = runningJob(year)
        vi.mocked(exportsApi.fetchAnnualStatementExports).mockResolvedValue([running])
        vi.mocked(exportsApi.fetchExportJob).mockRejectedValue(new Error('backend unreachable'))

        const { container, unmount } = renderCard('zev-1', year)
        try {
            await flush()
            await flush()

            // Five consecutive failures at 2.5 s each before the card gives up.
            await waitFor(
                () => container.textContent.includes('pages.reports.annualStatement.error'),
                'failed state after repeated poll errors',
                20000,
            )
            expect(container.textContent).not.toContain('pages.reports.annualStatement.preparing')
        } finally {
            unmount()
        }
    }, 30000)

    it('a failed job surfaces the backend error_message', async () => {
        const year = new Date().getFullYear() - 1
        const running = runningJob(year)
        vi.mocked(exportsApi.fetchAnnualStatementExports).mockResolvedValue([running])
        vi.mocked(exportsApi.fetchExportJob).mockResolvedValue({
            ...running,
            status: 'failed',
            error_message: 'The export did not finish. Prepare a new export to try again.',
        })

        const { container, unmount } = renderCard('zev-1', year)
        try {
            await flush()
            await flush()

            await waitFor(
                () =>
                    container.textContent.includes(
                        'The export did not finish. Prepare a new export to try again.',
                    ),
                'backend error message shown',
                8000,
            )
        } finally {
            unmount()
        }
    }, 12000)
})

describe('AnnualStatementsExportCard selection guards', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
    })

    function renderCard(zevId: string, year: number) {
        const container = document.createElement('div')
        document.body.appendChild(container)
        const client = new QueryClient()
        const root = createRoot(container)

        const render = (id: string, y: number) =>
            createElement(
                QueryClientProvider,
                { client },
                createElement(AnnualStatementsExportCard, { zevId: id, year: y, enabled: true }),
            )

        act(() => {
            root.render(render(zevId, year))
        })
        return {
            container,
            rerender: (id: string, y: number) => act(() => {
                root.render(render(id, y))
            }),
            unmount: () => {
                act(() => root.unmount())
                container.remove()
            },
        }
    }

    it('switching ZEV clears the previous ZEV job instead of showing it', async () => {
        const year = new Date().getFullYear() - 1
        const zevAJob = makeCompletedJob({ id: 'job-A', zev_id: 'zev-a', params: { year } })
        vi.mocked(exportsApi.fetchAnnualStatementExports).mockImplementation((zevId: string) =>
            Promise.resolve(zevId === 'zev-a' ? [zevAJob] : []),
        )

        const { container, rerender, unmount } = renderCard('zev-a', year)
        await flush()
        await flush()
        expect(findButton(container, 'pages.reports.annualStatement.downloadAll')).toBeTruthy()

        await rerender('zev-b', year)
        await flush()
        await flush()

        expect(findButton(container, 'pages.reports.annualStatement.downloadAll')).toBeUndefined()
        expect(findButton(container, 'pages.reports.annualStatement.prepare')).toBeTruthy()
        unmount()
    })

    it('a delayed create response is discarded after switching ZEV', async () => {
        const year = new Date().getFullYear() - 1
        vi.mocked(exportsApi.fetchAnnualStatementExports).mockResolvedValue([])
        let resolveCreate: (job: ExportJob) => void = () => undefined
        vi.mocked(exportsApi.createAnnualStatementsExport).mockImplementation(
            () =>
                new Promise<ExportJob>((resolve) => {
                    resolveCreate = resolve
                }),
        )

        const { container, rerender, unmount } = renderCard('zev-a', year)
        await flush()
        await flush()
        const prepareButton = findButton(container, 'pages.reports.annualStatement.prepare')!
        await click(prepareButton)
        expect(exportsApi.createAnnualStatementsExport).toHaveBeenCalledTimes(1)

        await rerender('zev-b', year)
        await flush()

        await act(async () => {
            resolveCreate(makeCompletedJob({ id: 'job-A', zev_id: 'zev-a', params: { year } }))
        })
        await flush()

        expect(findButton(container, 'pages.reports.annualStatement.downloadAll')).toBeUndefined()
        expect(findButton(container, 'pages.reports.annualStatement.prepare')).toBeTruthy()
        unmount()
    })
})
