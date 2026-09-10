import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuditLogsPage } from '../src/pages/AdminAuditLogsPage'

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

const fetchAuditEvents = vi.fn()
const fetchAuditEvent = vi.fn()

vi.mock('../src/lib/api/audit', () => ({
    fetchAuditEvents: (...args: unknown[]) => fetchAuditEvents(...args),
    fetchAuditEvent: (...args: unknown[]) => fetchAuditEvent(...args),
    fetchAuditFilterOptions: () => Promise.resolve({
        zevs: [
            { id: 'z1', name: 'Z1' },
            { id: 'z2', name: 'Z2' },
        ],
        actors: [],
    }),
}))

const emptyPage = { results: [], count: 0, next: null, previous: null }

const sampleEvent = {
    id: 'e1',
    created_at: '2026-01-01',
    summary: 'Did something',
    zev: 'z1',
    action_category: 'metering',
    action_type: 'metering_point.update',
    target_display: 'meter',
    target_type: 'zev.MeteringPoint',
    target_id: 'm1',
    actor_display: 'owner',
    status: 'success',
}

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
}

function mockSelection(selectedZevId: string | null) {
    mockManagedZev.mockReturnValue({
        managedZevs: selectedZevId ? [{ id: selectedZevId }] : [],
        selectedZevId,
        selectedZev: selectedZevId ? { id: selectedZevId, name: selectedZevId === 'z1' ? 'Z1' : 'Z2' } : null,
        isSelectable: false,
        isLoading: false,
        setSelectedZevId: vi.fn(),
    })
}

function renderAuditLogs(scope: 'admin' | 'owner') {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const root = createRoot(container)
    const ui = () =>
        createElement(
            MantineProvider,
            null,
            createElement(QueryClientProvider, { client }, createElement(AuditLogsPage, { scope })),
        )
    return {
        container,
        mount: async () => {
            await act(async () => {
                root.render(ui())
            })
            for (let i = 0; i < 100 && !container.querySelector('h2'); i += 1) {
                await act(async () => {
                    await new Promise((r) => setTimeout(r, 50))
                })
            }
            await act(async () => {
                await new Promise((r) => setTimeout(r, 0))
            })
        },
        rerender: async () => {
            await act(async () => {
                root.render(ui())
            })
            await act(async () => {
                await new Promise((r) => setTimeout(r, 0))
            })
        },
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

async function click(element: Element) {
    await act(async () => {
        ;(element as HTMLElement).click()
    })
    await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
    })
}

function buttonByText(container: HTMLElement, text: string) {
    const buttons = Array.from(container.querySelectorAll('button'))
    const found = buttons.find((b) => b.textContent === text)
    if (!found) throw new Error(`button "${text}" not found`)
    return found
}

async function waitForButton(container: HTMLElement, text: string) {
    for (let i = 0; i < 100; i += 1) {
        const found = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === text)
        if (found) return found
        await act(async () => {
            await new Promise((r) => setTimeout(r, 50))
        })
    }
    throw new Error(`button "${text}" not found`)
}

describe('audit log community scope', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
        fetchAuditEvents.mockResolvedValue(emptyPage)
        fetchAuditEvent.mockResolvedValue({ id: 'e1' })
    })

    it('owner request is scoped to the global selection', async () => {
        mockOwner()
        mockSelection('z1')
        const page = renderAuditLogs('owner')
        await page.mount()
        expect(fetchAuditEvents).toHaveBeenCalled()
        const arg = fetchAuditEvents.mock.calls.at(-1)?.[0] as Record<string, unknown>
        expect(arg.zev).toBe('z1')
        expect(arg.page).toBe(1)
        page.unmount()
    })

    it('owner view has no independent community selector', async () => {
        mockOwner()
        mockSelection('z1')
        const page = renderAuditLogs('owner')
        await page.mount()
        const labels = Array.from(page.container.querySelectorAll('label')).map((l) => l.textContent)
        expect(labels.some((text) => text?.includes('pages.auditLogs.filters.zev'))).toBe(false)
        page.unmount()
    })

    it('switching communities rescopes the request and resets the page', async () => {
        mockOwner()
        mockSelection('z1')
        fetchAuditEvents.mockResolvedValue({ results: [sampleEvent], count: 2, next: 'page-2', previous: null })
        const page = renderAuditLogs('owner')
        await page.mount()
        await click(await waitForButton(page.container, 'pages.auditLogs.pagination.next'))
        expect((fetchAuditEvents.mock.calls.at(-1)?.[0] as Record<string, unknown>).page).toBe(2)

        mockSelection('z2')
        await page.rerender()
        const arg = fetchAuditEvents.mock.calls.at(-1)?.[0] as Record<string, unknown>
        expect(arg.zev).toBe('z2')
        expect(arg.page).toBe(1)
        page.unmount()
    })

    it('switching communities closes the open event drawer', async () => {
        mockOwner()
        mockSelection('z1')
        fetchAuditEvents.mockResolvedValue({
            results: [sampleEvent],
            count: 1,
            next: null,
            previous: null,
        })
        const page = renderAuditLogs('owner')
        await page.mount()
        const row = page.container.querySelector('tbody tr')
        expect(row).toBeTruthy()
        await click(row!)
        expect(fetchAuditEvent).toHaveBeenCalledTimes(1)

        mockSelection('z2')
        await page.rerender()
        expect(fetchAuditEvent).toHaveBeenCalledTimes(1)
        page.unmount()
    })

    it('clearing filters keeps the community scope', async () => {
        mockOwner()
        mockSelection('z1')
        fetchAuditEvents.mockResolvedValue({ results: [sampleEvent], count: 2, next: 'page-2', previous: null })
        const page = renderAuditLogs('owner')
        await page.mount()
        await click(await waitForButton(page.container, 'pages.auditLogs.pagination.next'))
        await click(buttonByText(page.container, 'pages.auditLogs.actions.clearFilters'))
        const arg = fetchAuditEvents.mock.calls.at(-1)?.[0] as Record<string, unknown>
        expect(arg.zev).toBe('z1')
        expect(arg.page).toBe(1)
        page.unmount()
    })

    it('no request fires without a valid selection', async () => {
        mockOwner()
        mockSelection(null)
        const page = renderAuditLogs('owner')
        await page.mount()
        expect(fetchAuditEvents).not.toHaveBeenCalled()
        expect(page.container.textContent).toContain('pages.auditLogs.empty')
        page.unmount()
    })

    it('admin view keeps its community selector and sends the chosen zev', async () => {
        mockAdmin()
        mockSelection(null)
        const page = renderAuditLogs('admin')
        await page.mount()
        const selects = Array.from(page.container.querySelectorAll('select'))
        const zevSelect = selects.find((s) =>
            Array.from(s.options).some((o) => o.value === 'z2'),
        ) as HTMLSelectElement
        expect(zevSelect).toBeTruthy()
        await act(async () => {
            zevSelect.value = 'z2'
            zevSelect.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
        })
        const arg = fetchAuditEvents.mock.calls.at(-1)?.[0] as Record<string, unknown>
        expect(arg.zev).toBe('z2')
        page.unmount()
    })
})
