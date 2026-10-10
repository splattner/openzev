import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en', changeLanguage: vi.fn() } }),
}))

const mockAuth = vi.fn()
const mockManagedZev = vi.fn()

vi.mock('../src/lib/auth', () => ({ useAuth: () => mockAuth() }))
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => mockManagedZev(), useOptionalManagedZev: () => mockManagedZev() }))

import { PageHeader } from '../src/components/PageHeader'
import { PageState } from '../src/components/PageState'
import { Notice } from '../src/components/Notice'
import { ScopeGuard } from '../src/components/ScopeGuard'
import { Toolbar } from '../src/components/Toolbar'
import { StatCard } from '../src/components/StatCard'

const mounted: Array<() => void> = []

function render(node: ReactNode) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => {
        root.render(
            createElement(
                MemoryRouter,
                null,
                createElement(MantineProvider, null, node),
            ),
        )
    })
    const cleanup = () => {
        act(() => root.unmount())
        container.remove()
    }
    mounted.push(cleanup)
    // MantineProvider inlines its CSS-in-JS as a <style> node inside the tree,
    // so raw textContent would include the whole stylesheet.
    const text = () => {
        const clone = container.cloneNode(true) as HTMLElement
        clone.querySelectorAll('style').forEach((node) => node.remove())
        return clone.textContent ?? ''
    }
    return { container, text, unmount: cleanup }
}

afterEach(() => {
    mounted.splice(0).forEach((cleanup) => cleanup())
    document.body.innerHTML = ''
    vi.clearAllMocks()
})

function session(relation: 'admin' | 'manager' | 'viewer' | 'participant' | 'former' | 'none') {
    mockAuth.mockReturnValue({ user: { id: 1, role: relation === 'admin' ? 'admin' : 'user', first_name: 'A', last_name: 'B' }, relation })
}

function zevState(overrides: Record<string, unknown> = {}) {
    mockManagedZev.mockReturnValue({
        managedZevs: [],
        selectedZevId: '',
        selectedZev: null,
        isSelectable: false,
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
        relation: mockAuth().relation === 'none' ? undefined : mockAuth().relation,
        setSelectedZevId: vi.fn(),
        ...overrides,
    })
    return mockManagedZev()
}

describe('PageHeader', () => {
    it('renders the page title as the document h1', () => {
        const page = render(createElement(PageHeader, { title: 'Invoices' }))
        const headings = page.container.querySelectorAll('h1')
        expect(headings.length).toBe(1)
        expect(headings[0].textContent).toBe('Invoices')
    })

    it('hides the scope line and description when they are empty', () => {
        const page = render(createElement(PageHeader, { title: 'Invoices', eyebrow: '', description: undefined }))
        expect(page.container.querySelector('.eyebrow')).toBeNull()
        expect(page.container.querySelector('.muted')).toBeNull()
    })

    it('renders page actions beside the title', () => {
        const page = render(
            createElement(PageHeader, {
                title: 'Participants',
                actions: createElement('button', { className: 'button' }, 'New'),
            }),
        )
        expect(page.container.querySelector('.page-header-actions button')?.textContent).toBe('New')
    })
})

describe('Notice', () => {
    it('prevents another retry while the request is running', () => {
        const onRetry = vi.fn()
        const page = render(createElement(Notice, { tone: 'error', onRetry, isRetrying: true }, 'Failed'))
        const button = page.container.querySelector('button')!
        expect(button.disabled).toBe(true)
        expect(button.getAttribute('aria-busy')).toBe('true')
        expect(button.textContent).toBe('common.loading')
        act(() => button.click())
        expect(onRetry).not.toHaveBeenCalled()
    })
    it('offers a translated retry action that calls the supplied handler', () => {
        const onRetry = vi.fn()
        const page = render(createElement(Notice, { tone: 'error', onRetry }, 'Failed'))
        const button = page.container.querySelector('button')!
        expect(button.textContent).toBe('common.retry')
        act(() => button.click())
        expect(onRetry).toHaveBeenCalledOnce()
    })
    it('renders an error as an alert banner carrying the card surface', () => {
        const page = render(createElement(Notice, { tone: 'error' }, 'Boom'))
        const banner = page.container.querySelector('.error-banner')
        expect(banner?.getAttribute('role')).toBe('alert')
        expect(banner?.className).toContain('card')
    })

    it('renders warnings as status, not alerts', () => {
        const page = render(createElement(Notice, { tone: 'warning' }, 'Careful'))
        const banner = page.container.querySelector('.warning-banner')
        expect(banner?.getAttribute('role')).toBe('status')
    })

    it('can announce a persistent error count as status', () => {
        const page = render(createElement(Notice, { tone: 'error', role: 'status' }, '3 deliveries failed'))
        expect(page.container.querySelector('[role="status"]')?.textContent).toBe('3 deliveries failed')
        expect(page.container.querySelector('[role="alert"]')).toBeNull()
    })
})

describe('PageState', () => {
    const content = createElement('p', null, 'content')

    it('shows content when nothing else applies', () => {
        const page = render(createElement(PageState, null, content))
        expect(page.text()).toBe('content')
    })

    it('lets an error win over a pending load', () => {
        const page = render(createElement(PageState, { isError: true, isLoading: true, error: 'failed' }, content))
        expect(page.text()).toBe('failed')
        expect(page.container.querySelector('.error-banner')).not.toBeNull()
        expect(page.container.querySelector('.skeleton-block')).toBeNull()
    })

    it('replaces content with the initial loading skeleton', () => {
        const page = render(
            createElement(PageState, {
                isLoading: true,
                skeleton: 'table',
            }, content),
        )
        expect(page.container.querySelector('.skeleton-block')).not.toBeNull()
        expect(page.text()).not.toContain('content')
    })

    it('provides translated error copy when none is supplied', () => {
        const page = render(createElement(PageState, { isError: true }, content))
        expect(page.container.querySelector('[role="alert"]')?.textContent).toBe('common.error')
        expect(page.text()).not.toContain('content')
    })
})

describe('ScopeGuard', () => {
    it('blocks management content when the selected ID does not match its record', () => {
        session('manager')
        zevState({ selectedZevId: '42', selectedZev: { id: '43', name: 'Other community' } })
        const page = render(createElement(ScopeGuard, null, createElement('button', null, 'Export')))
        expect(page.text()).toContain('pages.guest.title')
        expect(page.container.querySelector('button')).toBeNull()
        expect(page.container.querySelector('.empty-state a')?.getAttribute('href')).toBe('/account')
    })
    it('passes participants through', () => {
        session('participant')
        zevState()
        const page = render(createElement(ScopeGuard, null, createElement('p', null, 'content')))
        expect(page.text()).toBe('content')
    })

    it('passes former participants through as well', () => {
        session('former')
        zevState()
        const page = render(createElement(ScopeGuard, null, createElement('p', null, 'content')))
        expect(page.text()).toBe('content')
    })

    it('renders children when a community is resolved', () => {
        session('manager')
        zevState({ selectedZevId: '42', selectedZev: { id: '42', name: 'Muster ZEV' } })
        const page = render(createElement(ScopeGuard, null, createElement('p', null, 'content')))
        expect(page.text()).toBe('content')
    })

    it('shows a skeleton while the community list loads', () => {
        session('admin')
        zevState({ isLoading: true })
        const page = render(createElement(ScopeGuard, { skeleton: 'table' }, createElement('p', null, 'content')))
        expect(page.container.querySelector('.skeleton-block')).not.toBeNull()
        expect(page.text()).not.toContain('content')
    })

    it('reports a failed community load instead of claiming there is none', () => {
        session('manager')
        const state = zevState({ isError: true })
        const page = render(createElement(ScopeGuard, null, createElement('p', null, 'content')))
        expect(page.text()).toContain('common.scopeGuard.loadFailed')
        expect(page.text()).not.toContain('pages.guest.title')
        const retry = page.container.querySelector('.error-banner button')
        expect(retry?.textContent).toBe('common.retry')
        act(() => retry?.dispatchEvent(new MouseEvent('click', { bubbles: true })))
        expect(state.refetch).toHaveBeenCalledTimes(1)
    })

    it('keeps content available after a failed refetch of a resolved community', () => {
        session('manager')
        const state = zevState({
            selectedZevId: '42',
            selectedZev: { id: '42', name: 'Muster ZEV' },
            isError: true,
        })
        const page = render(createElement(ScopeGuard, null, createElement('p', null, 'content')))
        expect(page.text()).toContain('content')
        expect(page.container.querySelector('[role="status"]')?.textContent).toContain('common.scopeGuard.refreshFailed')
        expect(page.container.querySelector('[role="alert"]')).toBeNull()
        act(() => page.container.querySelector('button')?.click())
        expect(state.refetch).toHaveBeenCalledTimes(1)
    })

    it('offers an admin without a community the way to create one', () => {
        session('admin')
        zevState()
        const page = render(createElement(ScopeGuard, null, createElement('p', null, 'content')))
        expect(page.text()).toContain('pages.zevs.emptyState.title')
        expect(page.container.querySelector('.empty-state a')?.getAttribute('href')).toBe('/admin/zevs')
    })

    it('explains missing access to an account without a community', () => {
        session('none')
        zevState()
        const page = render(createElement(ScopeGuard, null, createElement('p', null, 'content')))
        expect(page.text()).toContain('pages.guest.title')
        expect(page.container.querySelector('.empty-state a')?.getAttribute('href')).toBe('/account')
    })
})

describe('Toolbar', () => {
    it('puts filters and actions in one row', () => {
        const page = render(
            createElement(Toolbar, {
                actions: createElement('button', { className: 'button button-primary' }, 'New'),
            }, createElement('input', { 'aria-label': 'search' })),
        )
        expect(page.container.querySelector('.toolbar-main input')?.getAttribute('aria-label')).toBe('search')
        expect(page.container.querySelector('.toolbar-actions button')?.textContent).toBe('New')
    })

    it('omits a cluster that has nothing in it', () => {
        const page = render(createElement(Toolbar, { actions: createElement('button', null, 'New') }))
        expect(page.container.querySelector('.toolbar-main')).toBeNull()
        expect(page.container.querySelector('.toolbar-actions')).not.toBeNull()
    })

    it('does not add an unnamed group or an absent action cluster', () => {
        const page = render(createElement(Toolbar, { actions: null }, createElement('input')))
        expect(page.container.querySelector('[role="group"]')).toBeNull()
        expect(page.container.querySelector('.toolbar-actions')).toBeNull()
    })
})

describe('StatCard', () => {
    it('stays a plain section by default', () => {
        const page = render(createElement(StatCard, { label: 'Total', value: 3 }))
        expect(page.container.querySelector('section.stat-card h3')?.textContent).toBe('3')
        expect(page.container.querySelector('button')).toBeNull()
    })

    it('becomes a pressed toggle when it filters something', () => {
        const onPress = vi.fn()
        const page = render(createElement(StatCard, { label: 'Red', value: 2, tone: 'danger', onPress, pressed: true }))
        const button = page.container.querySelector('button.stat-card--interactive') as HTMLButtonElement
        expect(button.getAttribute('aria-pressed')).toBe('true')
        // No heading inside a button, but the value keeps its class.
        expect(button.querySelector('.stat-value')?.textContent).toBe('2')
        expect(button.querySelector('h3')).toBeNull()
        act(() => button.dispatchEvent(new MouseEvent('click', { bubbles: true })))
        expect(onPress).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['439.55 kWh', '439.55', 'kWh'],
        ['35.4 %', '35.4', '%'],
        ['CHF 1066.94', '1066.94', 'CHF'],
        ['CHF \u2212548.31', '\u2212548.31', 'CHF'],
        ['1066.94 CHF', '1066.94', 'CHF'],
    ])('sets the unit of %j apart from the figure, as the documents do', (value, figure, unit) => {
        const page = render(createElement(StatCard, { label: 'Figure', value }))
        const heading = page.container.querySelector('section.stat-card h3')!
        // The text (and so what assistive technology reads) is unchanged.
        expect(heading.textContent).toBe(value)
        expect(heading.querySelector('.stat-figure')?.textContent).toBe(figure)
        expect(heading.querySelector('.stat-unit')?.textContent).toBe(unit)
    })

    it.each(['—', '05.10.2026', '1 von 8', '8'])('keeps %j whole', (value) => {
        const page = render(createElement(StatCard, { label: 'Value', value }))
        const heading = page.container.querySelector('section.stat-card h3')!
        expect(heading.textContent).toBe(value)
        expect(heading.querySelector('.stat-unit')).toBeNull()
        expect(heading.querySelector('.stat-figure')?.textContent).toBe(value)
    })

    it('uses phrasing content for an unpressed toggle with a hint', () => {
        const page = render(createElement(StatCard, { label: 'Red', value: 2, hint: 'Missing readings', onPress: vi.fn(), pressed: false }))
        const button = page.container.querySelector('button')!
        expect(button.getAttribute('aria-pressed')).toBe('false')
        expect(button.querySelector('p, h3')).toBeNull()
        expect(button.textContent).toContain('Missing readings')
    })
})
