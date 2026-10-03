import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppRoutes } from '../src/components/AppRoutes'
import { ToastProvider } from '../src/lib/toast'

// The enrolment gate has its own tests (mfa.test.ts); the shell under test
// here is not what is being asserted about.
vi.mock('../src/components/MfaEnrolmentGate', () => ({
    MfaEnrolmentGate: ({ children }: { children: unknown }) => children,
}))

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
    useOptionalManagedZev: () => mockManagedZev(),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {}, isLoading: false }),
    formatShortDate: (d: string) => d,
    formatDateTime: (d: string) => d,
    toDayJsDateFormat: () => 'YYYY-MM-DD',
}))

vi.mock('../src/lib/api/audit', () => ({
    fetchAuditEvents: () => Promise.resolve({ results: [], count: 0, next: null, previous: null }),
    fetchAuditFilterOptions: () => Promise.resolve({ zevs: [], actors: [] }),
}))

vi.mock('../src/lib/api/metering', () => ({
    fetchChartData: () => Promise.resolve([]),
    fetchMeteringDataQualityStatus: () => Promise.resolve({ metering_points: [] }),
    fetchMeteringDashboardSummary: () => Promise.resolve({
        summary_kind: 'participant',
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
    downloadAnnualStatement: () => Promise.resolve(new Blob(['pdf'], { type: 'application/pdf' })),
    downloadFinancialSummary: () => Promise.resolve(new Blob(['pdf'], { type: 'application/pdf' })),
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
            role: 'user',
            must_change_password: false,
            preferred_zev: null,
        },
    })
    mockManagedZev.mockReturnValue({
        managedZevs: [{ id: 'z1', name: 'Selected ZEV' }],
        entries: [{ id: 'z1', name: 'Selected ZEV', relation: 'manager' }],
        relation: 'manager',
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
            preferred_zev: null,
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

/** A participant of `zevCount` communities, "Member ZEV" first and selected. */
function mockParticipant(zevCount = 1) {
    const names = ['Member ZEV', 'Other ZEV'].slice(0, zevCount)
    const memberships = names.map((name, index) => ({
        zev: `m${index + 1}`, zev_name: name, zev_disabled: false, access: null,
        participants: [{ id: `p${index + 1}`, valid_from: '2026-01-01', valid_to: null, live: true }],
    }))
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
            role: 'user',
            memberships,
            must_change_password: false,
            preferred_zev: null,
        },
    })
    mockManagedZev.mockReturnValue({
        managedZevs: [],
        entries: memberships.map((m) => ({ id: m.zev, name: m.zev_name, relation: 'participant' })),
        relation: 'participant',
        selectedZevId: 'm1',
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
    const router = createMemoryRouter([{ path: '*', element: createElement(AppRoutes) }], { initialEntries: [path] })
    await act(async () => {
        root.render(
            createElement(
                MantineProvider,
                null,
                createElement(ToastProvider, null,
                    createElement(QueryClientProvider,
                        { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
                        createElement(RouterProvider, { router }),
                    ),
                ),
            ),
        )
    })
    // The title renders during loading; wait for the page body too.
    for (let i = 0; i < 100 && (!container.querySelector('h1') || container.querySelector('.skeleton-block')); i += 1) {
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
        // The statement page embeds its annual documents on mount.
        vi.spyOn(URL, 'createObjectURL').mockImplementation(() => 'blob:eyebrow-1')
        vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    })

    afterEach(() => {
        mounted.forEach((cleanup) => cleanup())
        mounted.clear()
        document.body.innerHTML = ''
        vi.restoreAllMocks()
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

    it('metering points shows the selected community with several memberships', async () => {
        mockParticipant(2)
        const { container, unmount } = await renderAt('/metering-points')
        expect(container.querySelector('.page-stack .eyebrow')?.textContent).toBe('Member ZEV')
        unmount()
    })

    it('dashboard shows the participant community with a single membership', async () => {
        mockParticipant()
        const { container, unmount } = await renderAt('/')
        const eyebrow = container.querySelector('.page-stack .eyebrow')
        expect(eyebrow?.textContent).toBe('Member ZEV')
        unmount()
    })

    it('dashboard shows the selected community with several memberships', async () => {
        // The participant dashboard asks about the selected community (#761).
        mockParticipant(2)
        const { container, unmount } = await renderAt('/')
        expect(container.querySelector('.page-stack .eyebrow')?.textContent).toBe('Member ZEV')
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

    it('statement keeps the membership label with several memberships', async () => {
        // Both statement downloads ask about the selected community (#761).
        mockParticipant(2)
        const { container, unmount } = await renderAt('/me/statement')
        const eyebrow = container.querySelector('.page-stack .eyebrow')
        expect(eyebrow?.textContent).toBe('Member ZEV')
        unmount()
    })

    it('my invoices shows the community with a single membership', async () => {
        mockParticipant()
        const { container, unmount } = await renderAt('/me/invoices')
        const eyebrow = container.querySelector('.page-stack .eyebrow')
        expect(eyebrow?.textContent).toBe('Member ZEV')
        unmount()
    })
})
