import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout } from '../src/components/Layout'
import { fetchFeasibilityCalculatorEnabled } from '../src/lib/api/feasibility'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string, options?: { scope: string; label: string }) =>
            k === 'nav.scopedLabel' && options ? `${options.scope}: ${options.label}` : k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

const mockAuth = vi.fn()
const mockManagedZev = vi.fn()

vi.mock('../src/lib/auth', () => ({
    useAuth: () => mockAuth(),
}))

vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => mockManagedZev(),
    useOptionalManagedZev: () => mockManagedZev(),
}))

vi.mock('../src/lib/api/auth', () => ({
    fetchUsers: vi.fn(() => Promise.resolve([])),
}))

// Feasibility nav link visibility is gated by this flag (default off) —
// on here so the existing "admin/owner sees the link" assertions still
// exercise the rest of the nav rather than this one gate. The gate itself
// is covered by tests/feasibility-enabled.test.ts and the backend's
// TestFeasibilityCalculatorGate.
vi.mock('../src/lib/api/feasibility', () => ({
    fetchFeasibilityCalculatorEnabled: vi.fn(() => Promise.resolve(true)),
}))

vi.mock('../src/lib/toast', () => ({
    useToast: () => ({ pushToast: vi.fn() }),
}))

const ZEV = { id: 1, name: 'Muster ZEV', owner: 9 }
const SECOND_ZEV = { id: 2, name: 'Second ZEV', owner: 9 }

/** An admin, or a non-admin account managing or taking part in a community (#761). */
type Persona = 'admin' | 'manager' | 'viewer' | 'participant' | 'former' | 'none'

function mockSession(persona: Persona, impersonating = false, managedZevCount = 2) {
    const role = persona === 'admin' ? 'admin' : 'user'
    mockAuth.mockReturnValue({
        user: {
            id: 7,
            username: `${persona}@example.com`,
            email: `${persona}@example.com`,
            first_name: 'Test',
            last_name: 'User',
            role,
            must_change_password: false,
            preferred_zev: null,
            ...(impersonating ? { impersonated_by: { id: 1, username: 'admin' } } : {}),
        },
        logout: vi.fn(),
        isImpersonating: impersonating,
        impersonator: impersonating ? { id: 1, username: 'admin' } : null,
        stopImpersonation: vi.fn(),
    })
    // Participants have no managed ZEV selection. Two communities by default
    // so the sidebar switcher renders (it hides for exactly one — there is
    // nothing to switch).
    const manages = persona === 'admin' || persona === 'manager' || persona === 'viewer'
    const managedZevs = manages ? [ZEV, SECOND_ZEV].slice(0, managedZevCount) : []
    // What the provider lists for the switcher (#761): a manager's
    // communities, every one for an admin, a participant's one community.
    const entries = manages
        ? managedZevs.map((zev) => ({ id: zev.id, name: zev.name, relation: persona }))
        : persona === 'none' ? [] : [{ id: ZEV.id, name: ZEV.name, relation: persona }]
    mockManagedZev.mockReturnValue({
        managedZevs,
        entries,
        relation: entries[0]?.relation,
        selectedZevId: entries[0]?.id ?? '',
        selectedZev: manages && managedZevs.length > 0 ? ZEV : null,
        isSelectable: persona === 'admin' || entries.length > 1,
        isLoading: false,
        setSelectedZevId: vi.fn(),
    })
}

async function renderLayout() {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient()
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(
                MemoryRouter,
                null,
                createElement(QueryClientProvider, { client }, createElement(Layout)),
            ),
        )
    })
    // Let pending queries settle.
    await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
    })
    return {
        container,
        html: () => container.innerHTML,
        hasHref: (href: string) => container.querySelector(`a[href="${href}"]`) !== null,
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

async function renderLayoutAt(path: string) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient()
    const root = createRoot(container)
    const render = () => root.render(
        createElement(
            MemoryRouter,
            { initialEntries: [path] },
            createElement(QueryClientProvider, { client }, createElement(Layout)),
        ),
    )
    await act(async () => {
        render()
    })
    await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
    })
    return {
        container,
        html: () => container.innerHTML,
        link: (href: string) => container.querySelector(`a[href="${href}"]`),
        rerender: async () => { await act(async () => render()) },
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

function mockMobileViewport(initialMobile: boolean) {
    const matchMedia = window.matchMedia.bind(window)
    const media = Object.assign(new EventTarget(), {
        matches: initialMobile,
        media: '(max-width: 768px)',
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
    })
    const spy = vi.spyOn(window, 'matchMedia').mockImplementation((query) =>
        query === media.media ? media : matchMedia(query))
    return {
        change: (matches: boolean) => {
            media.matches = matches
            media.dispatchEvent(Object.assign(new Event('change'), { matches }))
        },
        restore: () => spy.mockRestore(),
    }
}

describe('role navigation (see docs/specs/2026-03-community-and-access.md §9.3)', () => {
    it('admin sees operational links, Setup, Feasibility and the consolidated Platform group', async () => {
        mockSession('admin')
        const page = await renderLayout()
        for (const href of [
            '/',
            '/dashboard',
            '/metering/chart',
            // Metering hub: chart/quality/imports are tabs of /metering/chart,
            // so only the hub entry appears in the nav.
            '/billing/invoices',
            '/reports',
            '/participants',
            '/metering/points',
            '/tariffs',
            '/zev-settings',
            '/feasibility',
            // Platform group has four hub entries:
            // Overview, Accounts (+ API keys tab), Templates, Settings.
            '/admin',
            '/admin/accounts',
            '/admin/templates',
            '/admin/system-settings',
        ]) {
            expect(page.hasHref(href)).toBe(true)
        }
        // Retired admin nav items no longer appear.
        for (const href of [
            '/admin/zevs',
            '/admin/api-keys',
            '/admin/invoices',
            '/admin/pdf-templates',
            '/admin/email-templates',
            '/admin/audit-logs',
            // Audit log moved into the ZEV settings hub (phase 3).
            '/audit-logs',
        ]) {
            expect(page.hasHref(href)).toBe(false)
        }
        // Only Setup and Platform carry group labels; the operational links
        // above them have no group heading. The community is chosen from the
        // page's scope line, not the sidebar.
        expect(page.html()).toContain('nav.setupGroup')
        expect(page.html()).toContain('nav.platformGroup')
        expect(page.container.querySelector('.community-switch')).toBeNull()
        // Two labelled groups, each rendered as a group for assistive tech.
        expect(page.container.querySelectorAll('nav [role="group"]').length).toBe(2)
        page.unmount()
    })

    it('hides the Feasibility link when the feature flag is off', async () => {
        vi.mocked(fetchFeasibilityCalculatorEnabled).mockResolvedValueOnce(false)
        mockSession('admin')
        const page = await renderLayout()

        expect(page.hasHref('/feasibility')).toBe(false)
        // Nothing else about the nav is affected — off by default is a
        // narrow gate on this one link, not a broader admin capability.
        expect(page.hasHref('/zev-settings')).toBe(true)
        expect(page.hasHref('/admin')).toBe(true)
        page.unmount()
    })

    it.each(['manager', 'viewer'] as const)('%s sees Reports and imports but no Platform group', async (persona) => {
        mockSession(persona)
        const page = await renderLayout()
        expect(page.hasHref('/metering/chart')).toBe(true)
        // Imports moved into the metering hub (phase 3): no standalone link.
        expect(page.hasHref('/metering/imports')).toBe(false)
        expect(page.hasHref('/dashboard')).toBe(true)
        expect(page.hasHref('/billing/invoices')).toBe(true)
        expect(page.hasHref('/reports')).toBe(true)
        // Audit log is a ZEV-settings tab now (deep link only).
        expect(page.hasHref('/audit-logs')).toBe(false)
        expect(page.hasHref('/zev-settings/audit')).toBe(false)
        expect(page.hasHref('/admin')).toBe(false)
        expect(page.html()).not.toContain('nav.platformGroup')
        page.unmount()
    })

    it('participant sees Dashboard, My invoices and Annual statement only', async () => {
        mockSession('participant')
        const page = await renderLayout()
        expect(page.hasHref('/')).toBe(true)
        expect(page.hasHref('/dashboard')).toBe(false)
        expect(page.hasHref('/me/invoices')).toBe(true)
        expect(page.hasHref('/me/statement')).toBe(true)
        for (const href of ['/reports', '/metering/imports', '/participants', '/tariffs', '/zev-settings', '/audit-logs', '/admin']) {
            expect(page.hasHref(href)).toBe(false)
        }
        // "My consumption" folded into the participant dashboard (phase 2):
        // no separate nav entry, deep link still works.
        expect(page.html()).not.toContain('nav.myConsumption')
        page.unmount()
    })

    it.each([false, true])('keeps former-participant invoice navigation accessible when collapsed=%s', async (collapsed) => {
        window.localStorage.setItem('openzev.sidebarCollapsed', String(collapsed))
        mockSession('former')
        const page = await renderLayout()
        try {
            const links = page.container.querySelectorAll('nav.nav-list a')
            expect(links).toHaveLength(1)
            expect(links[0].getAttribute('href')).toBe('/me/invoices')
            expect(links[0].getAttribute('aria-label') ?? links[0].textContent).toBe('nav.myInvoices')
            expect(links[0].getAttribute('title')).toBe(collapsed ? 'nav.myInvoices' : null)
        } finally {
            page.unmount()
        }
    })

    it('renders the avatar as initials rather than emoji', async () => {
        mockSession('admin')
        const page = await renderLayout()
        const userAvatar = page.container.querySelector('.sidebar-user .user-avatar')
        expect(userAvatar?.textContent).toBe('TU')
        page.unmount()
    })

    it.each([
        ['(v)ZEV Nord', 'VN'],
        ['🌞 Solar', 'S'],
        ['𐐨 Nord', '𐐀N'],
        ['ß Team', 'ST'],
        ['E\u0301nergie Nord', 'ÉN'],
        ['Genossenschaft', 'G'],
        ['', '·'],
        ['  ', '·'],
    ])('renders readable initials for %j', async (name, initials) => {
        mockSession('admin')
        Object.assign(mockAuth().user, { first_name: name, last_name: '', username: '' })
        const page = await renderLayout()
        try {
            expect(page.container.querySelector('.sidebar-user .user-avatar')?.textContent).toBe(initials)
        } finally {
            page.unmount()
        }
    })

    it('uses the username when the account has no name', async () => {
        mockSession('participant')
        Object.assign(mockAuth().user, { first_name: '', last_name: '', username: 'marina' })
        const page = await renderLayout()
        expect(page.container.querySelector('.sidebar-user .user-avatar')?.textContent).toBe('M')
        page.unmount()
    })

    it.each([false, true])('preserves link names and shows tooltips only when collapsed=%s', async (collapsed) => {
        window.localStorage.setItem('openzev.sidebarCollapsed', String(collapsed))
        mockSession('admin')
        const page = await renderLayout()
        try {
            for (const [href, key] of [
                ['/admin', 'nav.adminOverview'],
                ['/admin/accounts', 'nav.adminAccounts'],
                ['/admin/templates', 'nav.adminTemplates'],
                ['/admin/system-settings', 'nav.adminSystemSettings'],
            ]) {
                const link = page.container.querySelector(`nav a[href="${href}"]`)
                expect(link?.getAttribute('aria-label')).toBe(`nav.platformGroup: ${key}`)
                expect(link?.textContent).toBe(key)
            }
            function expectTooltips(shown: boolean) {
                for (const link of page.container.querySelectorAll('nav.nav-list a')) {
                    const scoped = link.getAttribute('href')?.startsWith('/admin')
                    const name = scoped ? link.getAttribute('aria-label') : link.textContent
                    expect(name).toBeTruthy()
                    expect(link.getAttribute('aria-label')).toBe(scoped || shown ? name : null)
                    expect(link.getAttribute('title')).toBe(shown ? name : null)
                }
            }
            expectTooltips(collapsed)
            const toggle = page.container.querySelector<HTMLButtonElement>('.sidebar-collapse-button')!
            await act(async () => toggle.click())
            expectTooltips(!collapsed)
        } finally {
            page.unmount()
            window.localStorage.removeItem('openzev.sidebarCollapsed')
        }
    })

    it.each([
        { role: 'admin', path: '/' },
        { role: 'admin', path: '/admin' },
        { role: 'participant', path: '/' },
        { role: 'none', path: '/' },
    ] as const)('ignores desktop collapse on mobile and restores it on desktop for $role at $path', async ({ role, path }) => {
        const viewport = mockMobileViewport(false)
        const previousOverflow = document.body.style.overflow
        let unmount: (() => void) | undefined
        try {
            document.body.style.overflow = 'auto'
            mockSession(role)
            const page = await renderLayoutAt(path)
            unmount = page.unmount
            await act(async () => page.container.querySelector<HTMLButtonElement>('.sidebar-collapse-button')!.click())
            expect(page.container.querySelector('.shell-collapsed')).not.toBeNull()
            await act(async () => viewport.change(true))
            expect(page.container.querySelector('.shell-collapsed')).toBeNull()
            expect(page.container.querySelector('.sidebar.collapsed')).toBeNull()
            await act(async () => page.container.querySelector<HTMLButtonElement>('.mobile-menu-button')!.click())
            expect(page.container.querySelector('.sidebar.mobile-open')).not.toBeNull()
            expect(document.body.style.overflow).toBe('hidden')
            expect(page.container.querySelector('nav a[title]')).toBeNull()
            page.container.querySelector<HTMLButtonElement>('.mobile-menu-button')!.focus()
            expect(window.localStorage.getItem('openzev.sidebarCollapsed')).toBe('true')
            await act(async () => viewport.change(false))
            expect(page.container.querySelector('.shell-collapsed')).not.toBeNull()
            expect(document.body.style.overflow).toBe('auto')
            expect(page.container.querySelector('.sidebar.mobile-open')).toBeNull()
            expect(document.activeElement).toBe(page.container.querySelector('.sidebar-collapse-button'))
            page.container.querySelector<HTMLAnchorElement>('nav a')!.focus()
            await act(async () => viewport.change(true))
            expect(page.container.querySelector('.sidebar.mobile-open')).toBeNull()
            expect(document.body.style.overflow).toBe('auto')
            expect(document.activeElement).toBe(page.container.querySelector('.mobile-menu-button'))
        } finally {
            unmount?.()
            viewport.restore()
            document.body.style.overflow = previousOverflow
            window.localStorage.removeItem('openzev.sidebarCollapsed')
        }
    })

    it.each([false, true])('preserves unrelated body focus on resize (previous navigation focus: %s)', async (previousNavigationFocus) => {
        const viewport = mockMobileViewport(true)
        let unmount: (() => void) | undefined
        try {
            window.localStorage.setItem('openzev.sidebarCollapsed', 'true')
            mockSession('admin')
            const page = await renderLayoutAt('/')
            unmount = page.unmount
            if (previousNavigationFocus) {
                const button = page.container.querySelector<HTMLButtonElement>('.mobile-menu-button')!
                await act(async () => {
                    button.focus()
                    button.blur()
                })
            }
            expect(document.activeElement).toBe(document.body)
            await act(async () => viewport.change(false))
            expect(document.activeElement).toBe(document.body)
        } finally {
            unmount?.()
            viewport.restore()
            window.localStorage.removeItem('openzev.sidebarCollapsed')
        }
    })

    it('ignores saved desktop collapse when mounted on mobile', async () => {
        const viewport = mockMobileViewport(true)
        let unmount: (() => void) | undefined
        try {
            window.localStorage.setItem('openzev.sidebarCollapsed', 'true')
            mockSession('none')
            const page = await renderLayoutAt('/')
            unmount = page.unmount
            expect(page.container.querySelector('.shell-collapsed')).toBeNull()
            expect(page.container.querySelector('nav a[title]')).toBeNull()
            expect(page.container.querySelector('.sidebar.mobile-open')).toBeNull()
            expect(window.localStorage.getItem('openzev.sidebarCollapsed')).toBe('true')
        } finally {
            unmount?.()
            viewport.restore()
            window.localStorage.removeItem('openzev.sidebarCollapsed')
        }
    })

    it('shows only account navigation for accounts without community access', async () => {
        mockSession('none')
        const page = await renderLayout()
        const hrefs = Array.from(page.container.querySelectorAll('nav.nav-list a'), (link) => link.getAttribute('href'))
        expect(hrefs).toEqual(['/account'])
        page.unmount()
    })

    it('keeps the impersonation banner while restyling the shell', async () => {
        mockSession('participant', true)
        const page = await renderLayout()
        expect(page.html()).toContain('impersonation-banner')
        expect(page.html()).toContain('nav.stopImpersonation')
        page.unmount()
    })

    it('closes the user menu on Escape', async () => {
        mockSession('admin')
        const page = await renderLayout()
        const trigger = page.container.querySelector('.sidebar-user .user-menu-trigger') as HTMLElement
        await act(async () => {
            trigger.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        expect(page.container.querySelector('#user-menu-list')).not.toBe(null)
        expect(document.activeElement?.getAttribute('href')).toBe('/account')
        await act(async () => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
        })
        expect(page.container.querySelector('#user-menu-list')).toBe(null)
        expect(document.activeElement).toBe(trigger)
        page.unmount()
    })

    it('keeps language selection available and closes the account panel when focus leaves', async () => {
        mockSession('admin')
        const page = await renderLayout()
        const trigger = page.container.querySelector('.sidebar-user .user-menu-trigger') as HTMLElement
        await act(async () => trigger.click())
        const languageButtons = Array.from(
            page.container.querySelectorAll<HTMLButtonElement>('.language-selector-button'),
        )
        expect(languageButtons.map((button) => button.textContent)).toEqual(
            expect.arrayContaining(['EN', 'DE', 'FR', 'IT']),
        )
        const french = languageButtons.find((button) => button.textContent === 'FR') as HTMLElement
        await act(async () => french.click())
        expect(mockAuth().logout).not.toHaveBeenCalled()
        expect(page.container.querySelector('#user-menu-list')).not.toBe(null)
        await act(async () => (page.container.querySelector('.mobile-menu-button') as HTMLElement).focus())
        expect(page.container.querySelector('#user-menu-list')).toBe(null)
        expect(trigger.getAttribute('aria-expanded')).toBe('false')
        page.unmount()
    })

    it('returns focus to the mobile menu button when Escape closes the drawer', async () => {
        mockSession('admin')
        const page = await renderLayout()
        const mobileButton = page.container.querySelector('.mobile-menu-button') as HTMLElement
        await act(async () => mobileButton.click())
        expect(mobileButton.getAttribute('aria-expanded')).toBe('true')
        page.container.querySelector<HTMLAnchorElement>('nav a')!.focus()
        await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
        expect(mobileButton.getAttribute('aria-expanded')).toBe('false')
        expect(document.activeElement).toBe(mobileButton)
        page.unmount()
    })

    it('expands the collapsed sidebar before opening the account panel at its foot', async () => {
        window.localStorage.setItem('openzev.sidebarCollapsed', 'true')
        try {
            mockSession('admin')
            const page = await renderLayout()
            const trigger = page.container.querySelector('.sidebar-footer .sidebar-user .user-menu-trigger') as HTMLElement
            // Collapsed, the trigger is the avatar alone and names the account.
            expect(trigger.getAttribute('title')).toBe('Test User')
            await act(async () => trigger.click())
            expect(page.container.querySelector('.shell.shell-collapsed')).toBe(null)
            expect(page.container.querySelector('#user-menu-list')).not.toBe(null)
            expect(document.activeElement?.getAttribute('href')).toBe('/account')
            page.unmount()
        } finally {
            window.localStorage.removeItem('openzev.sidebarCollapsed')
        }
    })

    it('ends the sidebar with the account, and the account panel with the source link', async () => {
        mockSession('admin')
        const page = await renderLayout()
        const footer = page.container.querySelector('.sidebar-footer') as HTMLElement
        const trigger = footer.querySelector<HTMLButtonElement>('.user-menu-trigger')!
        expect(Array.from(footer.querySelectorAll('a[href], button'))).toEqual([trigger])
        expect(page.container.querySelector('.top-nav .user-menu')).toBeNull()
        await act(async () => trigger.click())
        const panel = Array.from(footer.querySelectorAll<HTMLElement>('#user-menu-list a[href], #user-menu-list > button'))
        const source = panel.at(-1)!
        expect(source.classList.contains('user-menu-about')).toBe(true)
        expect(source.getAttribute('href')).toBe('https://github.com/splattner/openzev')
        expect(source.getAttribute('rel')).toBe('noopener noreferrer')
        page.unmount()
    })

})

describe('active navigation state is exposed to assistive tech', () => {
    it('marks the visually active nav entry with aria-current (hub sub-routes included)', async () => {
        mockSession('admin')
        const page = await renderLayoutAt('/metering/quality')
        const metering = page.link('/metering/chart')
        // The custom `active` prop drives both the class and the attribute.
        // Hub entries active on a sub-route use aria-current="true" so screen
        // readers don't announce the parent as the current document.
        expect(metering?.className).toContain('active')
        expect(metering?.getAttribute('aria-current')).toBe('true')
        // Non-active entries carry no aria-current.
        expect(page.link('/billing/invoices')?.getAttribute('aria-current')).toBe(null)
        expect(page.link('/')?.getAttribute('aria-current')).toBe(null)
        page.unmount()
    })

    it('keeps class and aria-current aligned on hub sub-routes too', async () => {
        mockSession('admin')
        const page = await renderLayoutAt('/billing/emails')
        const billing = page.link('/billing/invoices')
        expect(billing?.className).toContain('active')
        expect(billing?.getAttribute('aria-current')).toBe('true')
        page.unmount()
    })

    it('keeps Overview inactive on the Energy balance page', async () => {
        mockSession('manager')
        const page = await renderLayoutAt('/dashboard')
        expect(page.link('/dashboard')?.getAttribute('aria-current')).toBe('page')
        expect(page.link('/')?.getAttribute('aria-current')).toBe(null)
        page.unmount()
    })

    it.each(['/admin/overview', '/admin/zevs', '/admin/invoices', '/admin/dynamic-sources', '/admin/audit', '/admin/health'])(
        'keeps Overview active at %s', async (path) => {
            mockSession('admin')
            const page = await renderLayoutAt(path)
            expect(page.link('/admin')?.getAttribute('aria-current')).toBe('true')
            expect(page.container.querySelectorAll('a[aria-current]')).toHaveLength(1)
            page.unmount()
        },
    )

    it('marks the account card as the current place on the account page only', async () => {
        mockSession('manager')
        const page = await renderLayoutAt('/account')
        const trigger = page.container.querySelector('.sidebar-user .user-menu-trigger')
        expect(trigger?.classList.contains('is-current')).toBe(true)
        page.unmount()
        const other = await renderLayoutAt('/tariffs')
        expect(other.container.querySelector('.sidebar-user .user-menu-trigger')?.classList.contains('is-current')).toBe(false)
        other.unmount()
    })

    it('exactly one nav entry is current, never the dashboard on a sub-page', async () => {
        mockSession('admin')
        const page = await renderLayoutAt('/tariffs')
        const current = Array.from(page.container.querySelectorAll('a[aria-current]'))
        expect(current).toHaveLength(1)
        expect(current[0].getAttribute('href')).toBe('/tariffs')
        expect(current[0].getAttribute('aria-current')).toBe('page')
        page.unmount()
    })
})

describe('scope context stays visible in every layout', () => {
    it.each(['/tariffs', '/admin/zevs'])('names no scope in the sidebar at %s — the page scope line does', async (path) => {
        mockSession('admin')
        const page = await renderLayoutAt(path)
        const sidebar = page.container.querySelector('#app-sidebar')!
        expect(sidebar.textContent).not.toContain('Muster ZEV')
        expect(sidebar.textContent).not.toContain('nav.platformScope')
        expect(sidebar.querySelector('.community-switch')).toBe(null)
        page.unmount()
    })

    it('renders no header scope chip — the page scope line carries the context', async () => {
        mockSession('admin')
        const page = await renderLayoutAt('/tariffs')
        expect(page.container.querySelector('.header-scope-chip')).toBe(null)
        page.unmount()
    })
})
