import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppRoutes } from '../src/components/AppRoutes'
import { ToastProvider } from '../src/lib/toast'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string) => k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

const mockAuth = vi.fn()
const mockManagedZev = vi.fn()

vi.mock('../src/lib/auth', () => ({
    useAuth: () => mockAuth(),
}))

vi.mock('../src/lib/managedZev', () => ({
    ManagedZevProvider: (props: { children: unknown }) => props.children,
    useManagedZev: () => mockManagedZev(),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {}, isLoading: false }),
    formatShortDate: (d: string) => d,
    formatDateTime: (d: string) => d,
}))

vi.mock('../src/lib/api/audit', () => ({
    fetchAuditEvents: () => Promise.resolve({ results: [], count: 0, next: null, previous: null }),
    fetchAuditFilterOptions: () => Promise.resolve({ zevs: [], actors: [] }),
}))

vi.mock('../src/lib/api/metering', () => ({
    fetchChartData: () => Promise.resolve([]),
    fetchMeteringDataQualityStatus: () => Promise.resolve({ metering_points: [] }),
    fetchMeteringDashboardSummary: () => Promise.resolve({
        role: 'participant',
        bucket: 'day',
        totals: { consumed_from_zev_kwh: 0, imported_from_grid_kwh: 0, total_consumed_kwh: 0 },
        timeline: [],
        zev_totals: { produced_kwh: 0, consumed_kwh: 0, imported_kwh: 0, exported_kwh: 0 },
        zev_participant_stats: [],
        current_participant_id: null,
    }),
    fetchHourlyProfile: () => Promise.resolve({ hourly_profile: [] }),
}))

vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoices: () => Promise.resolve([]),
    deleteInvoice: vi.fn(() => Promise.resolve({})),
    openInvoicePdf: vi.fn(),
    fetchInvoice: () => Promise.resolve({
        id: 'inv-1',
        invoice_number: 'INV-001',
        zev: 'z2',
        zev_name: 'Invoice ZEV',
        participant: 'p1',
        participant_name: 'Anna Aar',
        period_start: '2026-01-01',
        period_end: '2026-01-31',
        status: 'sent',
        total_chf: '42.00',
        pdf_url: null,
    }),
    fetchInvoicePdfBlob: () => Promise.reject(new Error('no pdf')),
    generateInvoicePdf: () => Promise.resolve({}),
}))

vi.mock('../src/lib/api/zev', () => ({
    fetchZevs: () => Promise.resolve([]),
    createMeteringPoint: vi.fn(() => Promise.resolve({})),
    createMeteringPointAssignment: vi.fn(() => Promise.resolve({})),
    deleteMeteringPoint: vi.fn(() => Promise.resolve({})),
    deleteMeteringPointReadings: vi.fn(() => Promise.resolve({})),
    deleteMeteringPointAssignment: vi.fn(() => Promise.resolve({})),
    fetchMeteringPointAssignments: () => Promise.resolve([]),
    fetchMeteringPoints: () => Promise.resolve([]),
    fetchParticipants: () => Promise.resolve([]),
    updateMeteringPoint: vi.fn(() => Promise.resolve({})),
    updateMeteringPointAssignment: vi.fn(() => Promise.resolve({})),
}))

vi.mock('../src/lib/api/auth', () => ({
    fetchUsers: () => Promise.resolve([]),
}))

function mockOwner() {
    mockAuth.mockReturnValue({
        isAuthenticated: true,
        isLoading: false,
        isImpersonating: false,
        impersonator: null,
        user: {
            id: 9,
            username: 'owner@example.com',
            email: 'owner@example.com',
            first_name: '',
            last_name: '',
            role: 'zev_owner',
            must_change_password: false,
        },
    })
    mockManagedZev.mockReturnValue({
        managedZevs: [{ id: 'z1', name: 'Selected ZEV' }],
        selectedZevId: 'z1',
        selectedZev: { id: 'z1', name: 'Selected ZEV', billing_interval: 'monthly' },
        isSelectable: false,
        isLoading: false,
        setSelectedZevId: vi.fn(),
    })
}

function mockAdmin() {
    mockAuth.mockReturnValue({
        isAuthenticated: true,
        isLoading: false,
        isImpersonating: false,
        impersonator: null,
        user: {
            id: 1,
            username: 'admin@example.com',
            email: 'admin@example.com',
            first_name: '',
            last_name: '',
            role: 'admin',
            must_change_password: false,
        },
    })
    mockManagedZev.mockReturnValue({
        managedZevs: [],
        selectedZevId: null,
        selectedZev: null,
        isSelectable: false,
        isLoading: false,
        setSelectedZevId: vi.fn(),
    })
}

function mockParticipant(zevCount = 1) {
    mockAuth.mockReturnValue({
        isAuthenticated: true,
        isLoading: false,
        isImpersonating: false,
        impersonator: null,
        user: {
            id: 7,
            username: 'member@example.com',
            email: 'member@example.com',
            first_name: 'Anna',
            last_name: 'Aar',
            role: 'participant',
            zev_name: 'Member ZEV',
            zev_count: zevCount,
            must_change_password: false,
        },
    })
    mockManagedZev.mockReturnValue({
        managedZevs: [],
        selectedZevId: null,
        selectedZev: null,
        isSelectable: false,
        isLoading: false,
        setSelectedZevId: vi.fn(),
    })
}

async function renderAt(path: string) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(
                MemoryRouter,
                { initialEntries: [path] },
                createElement(
                    MantineProvider,
                    null,
                    createElement(
                        ToastProvider,
                        null,
                        createElement(
                            QueryClientProvider,
                            { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
                            createElement(AppRoutes),
                        ),
                    ),
                ),
            ),
        )
    })
    // Wait for the page shell (h2) and for any loading skeleton to clear:
    // since the metering-points redesign the loading branch already renders
    // an h2, so waiting for h2 alone can assert against the loading state.
    for (let i = 0; i < 100 && (!container.querySelector('h2') || container.querySelector('.mantine-Skeleton-root')); i += 1) {
        await act(async () => {
            await new Promise((r) => setTimeout(r, 50))
        })
    }
    const cleanup = () => {
        act(() => root.unmount())
        container.remove()
    }
    mounted.add(cleanup)
    return {
        container,
        unmount: () => {
            mounted.delete(cleanup)
            cleanup()
        },
    }
}

const mounted = new Set<() => void>()

describe('community eyebrow', { timeout: 30000 }, () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
    })

    afterEach(() => {
        mounted.forEach((cleanup) => cleanup())
        mounted.clear()
        document.body.innerHTML = ''
    })

    it('invoice detail shows the invoice community, not the global selection', async () => {
        mockOwner()
        const { container, unmount } = await renderAt('/billing/invoices/inv-1')
        const eyebrow = container.querySelector('.page-stack .eyebrow')
        expect(eyebrow?.textContent).toBe('Invoice ZEV')
        unmount()
    })

    it('metering points shows the participant community without a selection', async () => {
        mockParticipant()
        const { container, unmount } = await renderAt('/metering-points')
        const eyebrow = container.querySelector('.page-stack .eyebrow')
        expect(eyebrow?.textContent).toBe('Member ZEV')
        unmount()
    })

    it('metering points shows no community with several memberships', async () => {
        mockParticipant(2)
        const { container, unmount } = await renderAt('/metering-points')
        expect(container.querySelector('.page-stack .eyebrow')).toBeNull()
        unmount()
    })

    it('dashboard shows the participant community with a single membership', async () => {
        mockParticipant()
        const { container, unmount } = await renderAt('/')
        const eyebrow = container.querySelector('.page-stack .eyebrow')
        expect(eyebrow?.textContent).toBe('Member ZEV')
        unmount()
    })

    it('dashboard shows no community with several memberships', async () => {
        mockParticipant(2)
        const { container, unmount } = await renderAt('/')
        expect(container.querySelector('.page-stack .eyebrow')).toBeNull()
        unmount()
    })

    it('chart shows the participant community with a single membership', async () => {
        mockParticipant()
        const { container, unmount } = await renderAt('/metering/chart')
        const eyebrow = container.querySelector('.page-stack .eyebrow')
        expect(eyebrow?.textContent).toBe('Member ZEV')
        unmount()
    })

    it('chart shows no community with several memberships', async () => {
        mockParticipant(2)
        const { container, unmount } = await renderAt('/metering/chart')
        expect(container.querySelector('.page-stack .eyebrow')).toBeNull()
        unmount()
    })

    it('owner audit logs shows the selected community, not the role', async () => {
        mockOwner()
        const { container, unmount } = await renderAt('/audit-logs')
        const eyebrow = container.querySelector('.page-stack .eyebrow')
        expect(eyebrow?.textContent).toBe('Selected ZEV')
        unmount()
    })

    it('admin audit logs shows the platform label', async () => {
        mockAdmin()
        const { container, unmount } = await renderAt('/admin/audit-logs')
        const eyebrow = container.querySelector('.page-stack .eyebrow')
        expect(eyebrow?.textContent).toBe('nav.platformScope')
        unmount()
    })

    it('admin invoices shows the platform label', async () => {
        mockAdmin()
        const { container, unmount } = await renderAt('/admin/invoices')
        const eyebrow = container.querySelector('.page-stack .eyebrow')
        expect(eyebrow?.textContent).toBe('nav.platformScope')
        unmount()
    })
})
