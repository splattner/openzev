import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter, Outlet } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { AppRoutes } from '../src/components/AppRoutes'
import type { UserRole } from '../src/types/api'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string) => k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

const mockAuth = vi.fn()

vi.mock('../src/lib/auth', () => ({
    useAuth: () => mockAuth(),
}))

vi.mock('../src/lib/managedZev', () => ({
    ManagedZevProvider: (props: { children: unknown }) => props.children,
    useManagedZev: () => ({}),
}))

vi.mock('../src/components/Layout', () => ({
    Layout: () => createElement(Outlet),
}))

function marker(id: string) {
    return () => createElement('div', { 'data-testid': `page-${id}` }, id)
}

vi.mock('../src/pages/DashboardPage', () => ({ DashboardPage: marker('dashboard') }))
vi.mock('../src/pages/HomePage', () => ({ HomePage: marker('home') }))
vi.mock('../src/pages/AccountProfilePage', () => ({ AccountProfilePage: marker('account') }))
vi.mock('../src/pages/AdminDashboardPage', () => ({ AdminDashboardPage: marker('admin') }))
vi.mock('../src/pages/AdminSystemSettingsPage', () => ({ AdminSystemSettingsPage: marker('admin-system-settings') }))
vi.mock('../src/pages/AdminPdfTemplatesPage', () => ({ AdminPdfTemplatesPage: marker('admin-pdf-templates') }))
vi.mock('../src/pages/AdminEmailTemplatesPage', () => ({ AdminEmailTemplatesPage: marker('admin-email-templates') }))
vi.mock('../src/pages/AdminInvoicesPage', () => ({ AdminInvoicesPage: marker('admin-invoices') }))
vi.mock('../src/pages/AdminAuditLogsPage', () => ({ AuditLogsPage: marker('audit-logs') }))
vi.mock('../src/pages/AdminAccountsPage', () => ({ AdminAccountsPage: marker('admin-accounts') }))
vi.mock('../src/pages/AdminApiKeysPage', () => ({ AdminApiKeysPage: marker('admin-api-keys') }))
vi.mock('../src/pages/ZevListPage', () => ({ ZevListPage: marker('admin-zevs') }))
vi.mock('../src/pages/ParticipantsPage', () => ({ ParticipantsPage: marker('participants') }))
vi.mock('../src/pages/ZevSettingsPage', () => ({
    ZevSettingsPage: marker('zev-settings'),
    ZevSettingsTabRoute: marker('zev-settings'),
}))
vi.mock('../src/pages/MeteringPointsPage', () => ({ MeteringPointsPage: marker('metering-points') }))
vi.mock('../src/pages/MeteringChartPage', () => ({ MeteringChartPage: marker('metering-chart') }))
vi.mock('../src/pages/TariffsPage', () => ({ TariffsPage: marker('tariffs') }))
vi.mock('../src/pages/InvoicesPage', () => ({ InvoicesPage: marker('invoices') }))
vi.mock('../src/pages/MyInvoicesPage', () => ({ MyInvoicesPage: marker('my-invoices') }))
vi.mock('../src/pages/InvoiceDetailPage', () => ({ InvoiceDetailPage: marker('invoice-detail') }))
vi.mock('../src/pages/ReportsPage', () => ({ ReportsPage: marker('reports') }))
vi.mock('../src/pages/FeasibilityCalculatorPage', () => ({ FeasibilityCalculatorPage: marker('feasibility') }))
vi.mock('../src/pages/ImportsPage', () => ({ ImportsPage: marker('imports') }))
vi.mock('../src/pages/LoginPage', () => ({ LoginPage: marker('login') }))
vi.mock('../src/pages/VerifyEmailPage', () => ({ VerifyEmailPage: marker('verify-email') }))
vi.mock('../src/pages/OAuthCallbackPage', () => ({ OAuthCallbackPage: marker('oauth') }))
vi.mock('../src/pages/NotFoundPage', () => ({ NotFoundPage: marker('not-found') }))
// Hub shells (phase 3) render their first panel; the embedded page mocks
// above carry the markers.
vi.mock('../src/pages/BillingHubPage', () => ({ BillingHubPage: marker('billing-hub') }))
vi.mock('../src/pages/AdminOverviewHubPage', () => ({ AdminOverviewHubPage: marker('admin-overview-hub') }))
vi.mock('../src/pages/AdminAccountsHubPage', () => ({ AdminAccountsHubPage: marker('admin-accounts-hub') }))
vi.mock('../src/pages/AdminTemplatesHubPage', () => ({ AdminTemplatesHubPage: marker('admin-templates-hub') }))
vi.mock('../src/pages/AdminSystemHealthPanel', () => ({ AdminSystemHealthPanel: marker('admin-system-health') }))

function mockRole(role: UserRole) {
    mockAuth.mockReturnValue({
        isAuthenticated: true,
        isLoading: false,
        isImpersonating: false,
        impersonator: null,
        user: {
            id: 7,
            username: `${role}@example.com`,
            email: `${role}@example.com`,
            first_name: '',
            last_name: '',
            role,
            must_change_password: false,
            preferred_zev: null,
        },
    })
}

async function renderPath(path: string) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(
                MemoryRouter,
                { initialEntries: [path] },
                // Mantine context for the lazy-loading fallback (PageSkeleton).
                createElement(MantineProvider, null, createElement(AppRoutes)),
            ),
        )
    })
    return {
        shows: (id: string) => container.querySelector(`[data-testid="page-${id}"]`) !== null,
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

// path → [page marker when allowed] × per-role expectation.
// DENY lands on "/" (role-aware home marker) via ProtectedRoute — that is what
// makes a wrong guard fail here instead of staying green.
const MATRIX: Array<{ path: string; marker: string; allow: Record<UserRole, boolean> }> = [
    { path: '/dashboard', marker: 'dashboard', allow: { admin: true, zev_owner: true, participant: true } },
    { path: '/metering/chart', marker: 'metering-chart', allow: { admin: true, zev_owner: true, participant: true } },
    { path: '/metering/quality', marker: 'metering-chart', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/metering/imports', marker: 'metering-chart', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/metering-points', marker: 'metering-points', allow: { admin: true, zev_owner: true, participant: true } },
    { path: '/metering/points', marker: 'metering-points', allow: { admin: true, zev_owner: true, participant: true } },
    { path: '/billing/periods', marker: 'home', allow: { admin: true, zev_owner: true, participant: true } },
    { path: '/billing/invoices', marker: 'billing-hub', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/billing/emails', marker: 'billing-hub', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/billing/statements', marker: 'billing-hub', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/billing/invoices/42', marker: 'invoice-detail', allow: { admin: true, zev_owner: true, participant: true } },
    { path: '/me/statement', marker: 'reports', allow: { admin: false, zev_owner: false, participant: true } },
    { path: '/me/invoices', marker: 'my-invoices', allow: { admin: false, zev_owner: false, participant: true } },
    { path: '/reports', marker: 'reports', allow: { admin: true, zev_owner: true, participant: true } },
    { path: '/participants', marker: 'participants', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/tariffs', marker: 'tariffs', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/zev-settings', marker: 'zev-settings', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/zev-settings/audit', marker: 'zev-settings', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/feasibility', marker: 'feasibility', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/account', marker: 'account', allow: { admin: true, zev_owner: true, participant: true } },
    // Audit log lives in the ZEV settings hub now: legacy URL redirects into
    // the hub's audit tab (marker = the settings page).
    { path: '/audit-logs', marker: 'zev-settings', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/admin', marker: 'admin-overview-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/zevs', marker: 'admin-overview-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/invoices', marker: 'admin-overview-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/dynamic-sources', marker: 'admin-overview-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/audit', marker: 'admin-overview-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/audit-logs', marker: 'admin-overview-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/health', marker: 'admin-overview-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/accounts', marker: 'admin-accounts-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/accounts/api-keys', marker: 'admin-accounts-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/api-keys', marker: 'admin-accounts-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/templates', marker: 'admin-templates-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/templates/pdf', marker: 'admin-templates-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/pdf-templates', marker: 'admin-templates-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/email-templates', marker: 'admin-templates-hub', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/admin/system-settings', marker: 'admin-system-settings', allow: { admin: true, zev_owner: false, participant: false } },
    { path: '/metering', marker: 'metering-chart', allow: { admin: true, zev_owner: true, participant: true } },
    { path: '/billing', marker: 'billing-hub', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/invoices', marker: 'billing-hub', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/invoices/42', marker: 'invoice-detail', allow: { admin: true, zev_owner: true, participant: true } },
    { path: '/imports', marker: 'metering-chart', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/metering-data?tab=quality', marker: 'metering-chart', allow: { admin: true, zev_owner: true, participant: false } },
    { path: '/metering-data?metering_point=7', marker: 'metering-chart', allow: { admin: true, zev_owner: true, participant: true } },
]

describe('route guard matrix (tests AppRoutes, not the guard in isolation)', () => {
    it.each(MATRIX)('$path', async (row) => {
        const roles: UserRole[] = ['admin', 'zev_owner', 'participant']
        for (const role of roles) {
            mockRole(role)
            const page = await renderPath(row.path)
            if (row.allow[role]) {
                expect(page.shows(row.marker)).toBe(true)
                if (row.marker !== 'home') {
                    expect(page.shows('home')).toBe(false)
                }
            } else {
                expect(page.shows(row.marker)).toBe(false)
                expect(page.shows('home')).toBe(true)
            }
            page.unmount()
        }
    })
})
