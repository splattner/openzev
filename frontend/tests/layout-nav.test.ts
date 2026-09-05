import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Layout } from '../src/components/Layout'
import type { UserRole } from '../src/types/api'

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
    useManagedZev: () => mockManagedZev(),
}))

vi.mock('../src/lib/api/auth', () => ({
    fetchUsers: vi.fn(() => Promise.resolve([])),
}))

vi.mock('../src/lib/toast', () => ({
    useToast: () => ({ pushToast: vi.fn() }),
}))

const ZEV = { id: 1, name: 'Muster ZEV', owner: 9 }
const SECOND_ZEV = { id: 2, name: 'Second ZEV', owner: 9 }

function mockSession(role: UserRole, impersonating = false, managedZevCount = 2) {
    mockAuth.mockReturnValue({
        user: {
            id: 7,
            username: `${role}@example.com`,
            email: `${role}@example.com`,
            first_name: 'Test',
            last_name: 'User',
            role,
            must_change_password: false,
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
    const manages = role === 'admin' || role === 'zev_owner'
    mockManagedZev.mockReturnValue({
        managedZevs: manages ? [ZEV, SECOND_ZEV].slice(0, managedZevCount) : [],
        selectedZevId: manages ? 1 : '',
        selectedZev: manages ? ZEV : null,
        isSelectable: role === 'admin',
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
    await act(async () => {
        root.render(
            createElement(
                MemoryRouter,
                { initialEntries: [path] },
                createElement(QueryClientProvider, { client }, createElement(Layout)),
            ),
        )
    })
    await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
    })
    return {
        container,
        html: () => container.innerHTML,
        link: (href: string) => container.querySelector(`a[href="${href}"]`),
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

describe('flat nav (see docs/specs/2026-09-navigation-regroup.md §5)', () => {
    it('admin sees operate entries, Setup, Feasibility and the full Platform group', async () => {
        mockSession('admin')
        const page = await renderLayout()
        for (const href of [
            '/',
            '/metering/chart',
            '/metering/imports',
            '/billing/invoices',
            '/reports',
            '/participants',
            '/metering-points',
            '/tariffs',
            '/zev-settings',
            '/audit-logs',
            '/feasibility',
            '/admin',
            '/admin/zevs',
            '/admin/accounts',
            '/admin/api-keys',
            '/admin/invoices',
            '/admin/system-settings',
            '/admin/pdf-templates',
            '/admin/email-templates',
            '/admin/audit-logs',
        ]) {
            expect(page.hasHref(href)).toBe(true)
        }
        // Scope colouring: group labels + the ZEV switcher in the sidebar.
        expect(page.html()).toContain('nav.setupGroup')
        expect(page.html()).toContain('nav.platformGroup')
        expect(page.html()).toContain('sidebar-zev-menu')
        page.unmount()
    })

    it('owner sees Reports and imports but no Platform group', async () => {
        mockSession('zev_owner')
        const page = await renderLayout()
        expect(page.hasHref('/metering/chart')).toBe(true)
        expect(page.hasHref('/metering/imports')).toBe(true)
        expect(page.hasHref('/billing/invoices')).toBe(true)
        expect(page.hasHref('/reports')).toBe(true)
        expect(page.hasHref('/audit-logs')).toBe(true)
        expect(page.hasHref('/admin')).toBe(false)
        expect(page.html()).not.toContain('nav.platformGroup')
        page.unmount()
    })

    it('participant sees Dashboard, My invoices and Annual statement only', async () => {
        mockSession('participant')
        const page = await renderLayout()
        expect(page.hasHref('/')).toBe(true)
        expect(page.hasHref('/me/invoices')).toBe(true)
        expect(page.hasHref('/me/statement')).toBe(true)
        for (const href of ['/reports', '/metering/imports', '/participants', '/tariffs', '/zev-settings', '/audit-logs', '/admin']) {
            expect(page.hasHref(href)).toBe(false)
        }
        // "My consumption" folded into the participant dashboard (phase 2):
        // no separate nav entry, deep link still works.
        expect(page.html()).not.toContain('nav.myConsumption')
        // No switcher for participants.
        expect(page.html()).not.toContain('sidebar-zev-menu')
        page.unmount()
    })

    it('a single managed community renders no switcher — the page eyebrow carries the name', async () => {
        mockSession('zev_owner', false, 1)
        const page = await renderLayout()
        expect(page.html()).not.toContain('sidebar-zev-menu')
        expect(page.hasHref('/participants')).toBe(true)
        page.unmount()
    })

    it('names the collapsed ZEV switcher for assistive tech', async () => {
        window.localStorage.setItem('openzev.sidebarCollapsed', 'true')
        try {
            mockSession('admin')
            const page = await renderLayout()
            const trigger = page.container.querySelector('.sidebar-zev-menu .user-menu-trigger')
            expect(trigger?.getAttribute('aria-label')).toBe('nav.manageZevFor')
            expect(trigger?.getAttribute('aria-expanded')).toBe('false')
            expect(trigger?.getAttribute('aria-controls')).toBe('zev-menu-list')
            // Collapsed shell hides the text; the emoji carries no name.
            expect(page.container.querySelector('.shell.shell-collapsed')).not.toBe(null)
            expect(trigger?.querySelector('.user-avatar')?.getAttribute('aria-hidden')).toBe('true')
            page.unmount()
        } finally {
            window.localStorage.removeItem('openzev.sidebarCollapsed')
        }
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
        const trigger = page.container.querySelector('.top-nav .user-menu-trigger') as HTMLElement
        await act(async () => {
            trigger.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        expect(page.container.querySelector('#user-menu-list')).not.toBe(null)
        await act(async () => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
        })
        expect(page.container.querySelector('#user-menu-list')).toBe(null)
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
        const page = await renderLayoutAt('/billing/invoices/42')
        const billing = page.link('/billing/invoices')
        expect(billing?.className).toContain('active')
        expect(billing?.getAttribute('aria-current')).toBe('true')
        page.unmount()
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
    it('shows the platform scope chip instead of the ZEV switcher under /admin', async () => {
        mockSession('admin')
        const page = await renderLayoutAt('/admin/zevs')
        // Sidebar: chip present, switcher unmounted, ZEV name absent.
        expect(page.html()).toContain('nav.platformScope')
        expect(page.container.querySelector('.sidebar-scope-chip')).not.toBe(null)
        expect(page.container.querySelector('.sidebar-zev-menu')).toBe(null)
        expect(page.html()).not.toContain('Muster ZEV')
        page.unmount()
    })

    it('renders no header scope chip — page eyebrows and the sidebar block carry the context', async () => {
        mockSession('admin')
        const page = await renderLayoutAt('/tariffs')
        expect(page.container.querySelector('.header-scope-chip')).toBe(null)
        page.unmount()
    })
})
