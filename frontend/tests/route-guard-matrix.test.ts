import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter, Outlet, useLocation } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { AppRoutes } from '../src/components/AppRoutes'
import type { ShellRole } from '../src/lib/communityAccess'

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
const renderPage = vi.hoisted(() => vi.fn())

vi.mock('../src/lib/auth', () => ({
    useAuth: () => mockAuth(),
}))

const mockManaged = vi.fn(() => ({}))

vi.mock('../src/lib/managedZev', () => ({
    ManagedZevProvider: (props: { children: unknown }) => props.children,
    useManagedZev: () => mockManaged(),
    useOptionalManagedZev: () => mockManaged(),
}))

vi.mock('../src/components/Layout', () => ({
    Layout: () => createElement(Outlet),
}))

// Observe the period alias before navigation; both allowance and denial end at /.
vi.mock('../src/components/RouteAliases', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/components/RouteAliases')>()
    const PeriodsAliasMarker = marker('periods-alias')
    return {
        ...actual,
        AliasNavigate: ({ to }: { to: string }) => to === '/'
            ? createElement(PeriodsAliasMarker)
            : createElement(actual.AliasNavigate, { to }),
    }
})

function marker(id: string) {
    return function PageMarker() {
        renderPage(id)
        const { pathname, search, state } = useLocation()
        return createElement('div', {
            'data-testid': `page-${id}`,
            'data-location': `${pathname}${search}`,
            'data-location-state': JSON.stringify(state),
        }, id)
    }
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
vi.mock('../src/pages/ConfirmEmailChangePage', () => ({ ConfirmEmailChangePage: marker('confirm-email-change') }))
vi.mock('../src/pages/OAuthCallbackPage', () => ({ OAuthCallbackPage: marker('oauth') }))
vi.mock('../src/pages/ParticipantOnboardingPage', () => ({ ParticipantOnboardingPage: marker('join') }))
vi.mock('../src/pages/MagicSignInPage', () => ({ MagicSignInPage: marker('sign-in') }))
vi.mock('../src/pages/PublicInvoicePage', () => ({ PublicInvoicePage: marker('public-invoice') }))
vi.mock('../src/pages/NotFoundPage', () => ({ NotFoundPage: marker('not-found') }))
// Hub shells (phase 3) render their first panel; the embedded page mocks
// above carry the markers.
vi.mock('../src/pages/BillingHubPage', () => ({ BillingHubPage: marker('billing-hub') }))
vi.mock('../src/pages/AdminOverviewHubPage', () => ({ AdminOverviewHubPage: marker('admin-overview-hub') }))
vi.mock('../src/pages/AdminAccountsHubPage', () => ({ AdminAccountsHubPage: marker('admin-accounts-hub') }))
vi.mock('../src/pages/AdminTemplatesHubPage', () => ({ AdminTemplatesHubPage: marker('admin-templates-hub') }))
vi.mock('../src/pages/AdminSystemHealthPanel', () => ({ AdminSystemHealthPanel: marker('admin-system-health') }))

function mockPersona(persona: ShellRole) {
    const role = persona === 'admin' ? 'admin' : 'user'
    mockManaged.mockReturnValue(persona === 'none' ? {} : { relation: persona })
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
        location: () => container.querySelector('[data-location]')?.getAttribute('data-location'),
        state: () => JSON.parse(container.querySelector('[data-location-state]')?.getAttribute('data-location-state') ?? 'null'),
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

// path → [page marker when allowed] × per-role expectation.
// DENY lands on "/" (role-aware home marker) via ProtectedRoute — that is what
// makes a wrong guard fail here instead of staying green.
const MATRIX: Array<{ path: string; marker: string; allow: Record<ShellRole, boolean> }> = [
    { path: '/', marker: 'home', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: true } },
    { path: '/account/', marker: 'account', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: true } },
    { path: '/account?tab=security', marker: 'account', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: true } },
    { path: '/metering-data', marker: 'metering-chart', allow: { admin: true, manager: true, viewer: true, participant: true, former: false, none: false } },
    { path: '/verify-email?token=example', marker: 'verify-email', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: true } },
    { path: '/oauth/callback', marker: 'oauth', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: true } },
    { path: '/join/example?s=secret', marker: 'join', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: true } },
    { path: '/signin/example', marker: 'sign-in', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: true } },
    { path: '/i/example?s=secret', marker: 'public-invoice', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: true } },
    { path: '/dashboard', marker: 'dashboard', allow: { admin: true, manager: true, viewer: true, participant: true, former: false, none: false } },
    { path: '/metering/chart', marker: 'metering-chart', allow: { admin: true, manager: true, viewer: true, participant: true, former: false, none: false } },
    { path: '/metering/quality', marker: 'metering-chart', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/metering/imports', marker: 'metering-chart', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/metering-points', marker: 'metering-points', allow: { admin: true, manager: true, viewer: true, participant: true, former: false, none: false } },
    { path: '/metering/points', marker: 'metering-points', allow: { admin: true, manager: true, viewer: true, participant: true, former: false, none: false } },
    { path: '/billing/periods', marker: 'periods-alias', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/billing/invoices', marker: 'billing-hub', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/billing/emails', marker: 'billing-hub', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/billing/statements', marker: 'reports', allow: { admin: true, manager: true, viewer: true, participant: true, former: false, none: false } },
    { path: '/billing/invoices/42', marker: 'invoice-detail', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: false } },
    { path: '/me/statement', marker: 'reports', allow: { admin: false, manager: false, viewer: false, participant: true, former: false, none: false } },
    { path: '/me/invoices', marker: 'my-invoices', allow: { admin: false, manager: false, viewer: false, participant: true, former: true, none: false } },
    { path: '/reports', marker: 'reports', allow: { admin: true, manager: true, viewer: true, participant: true, former: false, none: false } },
    { path: '/participants', marker: 'participants', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/tariffs', marker: 'tariffs', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/zev-settings', marker: 'zev-settings', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/zev-settings/audit', marker: 'zev-settings', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/feasibility', marker: 'feasibility', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/account', marker: 'account', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: true } },
    // Audit log lives in the ZEV settings hub now: legacy URL redirects into
    // the hub's audit tab (marker = the settings page).
    { path: '/audit-logs', marker: 'zev-settings', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/admin', marker: 'admin-overview-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/zevs', marker: 'admin-overview-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/invoices', marker: 'admin-overview-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/dynamic-sources', marker: 'admin-overview-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/audit', marker: 'admin-overview-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/audit-logs', marker: 'admin-overview-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/health', marker: 'admin-overview-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/accounts', marker: 'admin-accounts-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/accounts/api-keys', marker: 'admin-accounts-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/api-keys', marker: 'admin-accounts-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/templates', marker: 'admin-templates-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/templates/pdf', marker: 'admin-templates-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/pdf-templates', marker: 'admin-templates-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/email-templates', marker: 'admin-templates-hub', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/admin/system-settings', marker: 'admin-system-settings', allow: { admin: true, manager: false, viewer: false, participant: false, former: false, none: false } },
    { path: '/metering', marker: 'metering-chart', allow: { admin: true, manager: true, viewer: true, participant: true, former: false, none: false } },
    { path: '/billing', marker: 'billing-hub', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/invoices', marker: 'billing-hub', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/invoices/42', marker: 'invoice-detail', allow: { admin: true, manager: true, viewer: true, participant: true, former: true, none: false } },
    { path: '/imports', marker: 'metering-chart', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/metering-data?tab=quality', marker: 'metering-chart', allow: { admin: true, manager: true, viewer: true, participant: false, former: false, none: false } },
    { path: '/metering-data?metering_point=7', marker: 'metering-chart', allow: { admin: true, manager: true, viewer: true, participant: true, former: false, none: false } },
]

describe('route guard matrix (tests AppRoutes, not the guard in isolation)', () => {
    const roles: ShellRole[] = ['admin', 'manager', 'viewer', 'participant', 'former', 'none']
    it.each(MATRIX.flatMap((row) => roles.map((role) => ({ ...row, role }))))('$role: $path', async (row) => {
        mockPersona(row.role)
        renderPage.mockClear()
        const page = await renderPath(row.path)
        try {
            if (row.allow[row.role]) {
                expect(page.shows(row.marker)).toBe(true)
                if (row.marker !== 'home') {
                    expect(page.shows('home')).toBe(false)
                }
            } else {
                expect(page.shows(row.marker)).toBe(false)
                expect(renderPage).not.toHaveBeenCalledWith(row.marker)
                expect(page.shows('home')).toBe(true)
            }
        } finally {
            page.unmount()
        }
    })

    it.each([
        { path: '/login', marker: 'login' },
        { path: '/verify-email?token=example', marker: 'verify-email' },
        { path: '/confirm-email-change?token=example', marker: 'confirm-email-change' },
        { path: '/oauth/callback', marker: 'oauth' },
        { path: '/join/example?s=secret', marker: 'join' },
        { path: '/signin/example', marker: 'sign-in' },
        { path: '/i/example?s=secret', marker: 'public-invoice' },
    ])('keeps $path outside the authentication guard', async (row) => {
        mockPersona('none')
        mockAuth.mockReturnValue({ ...mockAuth(), isAuthenticated: false, user: null })
        const page = await renderPath(row.path)
        try {
            expect(page.shows(row.marker)).toBe(true)
            expect(page.shows('home')).toBe(false)
        } finally {
            page.unmount()
        }
    })

    it.each([
        { path: '/', expected: '/account', state: { forcePasswordChange: true } },
        { path: '/dashboard', expected: '/account', state: { forcePasswordChange: true } },
        { path: '/metering/chart', expected: '/account', state: { forcePasswordChange: true } },
        { path: '/account?tab=profile', expected: '/account?tab=profile', state: null },
        { path: '/account/', expected: '/account/', state: null },
        { path: '/account/?tab=profile', expected: '/account/?tab=profile', state: null },
    ])(
        'keeps forced password-change access for an account without community access at $path', async ({ path, expected, state }) => {
            mockPersona('none')
            mockAuth().user.must_change_password = true
            const page = await renderPath(path)
            try {
                expect(page.shows('account')).toBe(true)
                expect(page.location()).toBe(expected)
                expect(page.state()).toEqual(state)
                expect(page.shows('dashboard')).toBe(false)
                expect(page.shows('metering-chart')).toBe(false)
            } finally {
                page.unmount()
            }
        },
    )
})

// #761: the guard follows the relation to the selected community. A viewer
// gets the management pages; a former participant only its invoices.
describe('route guard by relation to the selected community', () => {
    const cases: Array<{ relation: string; path: string; marker: string; allow: boolean }> = [
        { relation: 'viewer', path: '/participants', marker: 'participants', allow: true },
        { relation: 'viewer', path: '/tariffs', marker: 'tariffs', allow: true },
        { relation: 'viewer', path: '/zev-settings/access', marker: 'zev-settings', allow: true },
        { relation: 'viewer', path: '/me/statement', marker: 'reports', allow: false },
        { relation: 'manager', path: '/billing/invoices', marker: 'billing-hub', allow: true },
        { relation: 'former', path: '/me/invoices', marker: 'my-invoices', allow: true },
        { relation: 'former', path: '/me/statement', marker: 'reports', allow: false },
        { relation: 'former', path: '/participants', marker: 'participants', allow: false },
        { relation: 'former', path: '/dashboard', marker: 'dashboard', allow: false },
        { relation: 'former', path: '/metering/chart', marker: 'metering-chart', allow: false },
        { relation: 'former', path: '/metering/points', marker: 'metering-points', allow: false },
    ]

    it.each(cases)('$relation → $path', async ({ relation, path, marker, allow }) => {
        mockPersona('participant')
        mockManaged.mockReturnValue({ relation })
        try {
            const page = await renderPath(path)
            expect(page.shows(marker)).toBe(allow)
            if (!allow) expect(page.shows('home')).toBe(true)
            page.unmount()
        } finally {
            mockManaged.mockReturnValue({})
        }
    })
})
