import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { AdminSystemSettingsPage } from '../src/pages/AdminSystemSettingsPage'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/api/auth', () => ({
    createOAuthProviderConfig: vi.fn(),
    deleteOAuthProviderConfig: vi.fn(),
    fetchFeatureFlags: vi.fn().mockResolvedValue([]),
    fetchOAuthProviderConfigs: vi.fn().mockResolvedValue([]),
    updateAppSettings: vi.fn(),
    updateFeatureFlag: vi.fn(),
    updateOAuthProviderConfig: vi.fn(),
}))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return {
        ...actual,
        useAppSettings: () => ({
            settings: {
                date_format_short: 'dd.MM.yyyy',
                date_format_long: 'd. MMMM yyyy',
                date_time_format: 'dd.MM.yyyy HH:mm',
                updated_at: '2026-01-01T00:00:00Z',
            },
            isLoading: false,
        }),
    }
})
vi.mock('../src/features/settings/VatSettingsSection', () => ({
    VatSettingsSection: () => createElement('section', null, 'vat-stub'),
}))

function RoutedPage() {
    const location = useLocation()
    return createElement('div', null,
        createElement('output', null, location.pathname + location.search),
        createElement(AdminSystemSettingsPage),
    )
}

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function render(url: string) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    await act(async () => root.render(
        createElement(QueryClientProvider, { client },
            createElement(MantineProvider, null,
                createElement(MemoryRouter, { initialEntries: [url] }, createElement(RoutedPage)))),
    ))
    // Let the empty feature-flag / OAuth queries settle.
    for (let i = 0; i < 20 && !container.querySelector('form'); i++) {
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)) })
    }
    return container
}

const tab = (container: Element, value: string) =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
        .find((button) => button.textContent === `adminSystemSettings.tabs.${value}.label`)!

function activePanel(container: Element) {
    const activeTab = container.querySelector('[role="tab"][data-active]')!
    return container.ownerDocument.getElementById(activeTab.getAttribute('aria-controls')!)!
}

describe('system settings tab strip', () => {
    it('renders the standard tab strip with panels instead of a boxed strip', async () => {
        const container = await render('/admin/system-settings')
        const root = container.querySelector('.app-tabs')
        expect(root).not.toBeNull()
        const list = container.querySelector('.app-tabs-list')
        expect(list).not.toBeNull()
        expect(list!.closest('section')).toBeNull()
        const tabs = container.querySelectorAll('[role="tab"]')
        expect(tabs).toHaveLength(4)
        for (const tabElement of Array.from(tabs)) {
            expect(tabElement.classList.contains('app-tabs-tab')).toBe(true)
            const panel = container.querySelector(`#${tabElement.getAttribute('aria-controls')}`)
            expect(panel?.getAttribute('role')).toBe('tabpanel')
        }
        // Inactive panels render as empty shells (Mantine hides panel content
        // for inactive tabs in the test env); only the active panel has content.
        expect(container.querySelectorAll('[role="tabpanel"]')).toHaveLength(4)
        expect(tab(container, 'regional').hasAttribute('data-active')).toBe(true)
        expect(activePanel(container).textContent).toContain('adminSystemSettings.regional.title')
    })

    it('switches panels and defaults invalid tabs to regional', async () => {
        const container = await render('/admin/system-settings?tab=oauth')
        expect(tab(container, 'oauth').hasAttribute('data-active')).toBe(true)
        await act(async () => { tab(container, 'features').click() })
        expect(container.querySelector('output')?.textContent).toBe('/admin/system-settings?tab=features')
        expect(activePanel(container).textContent).toContain('features.title')
        expect(activePanel(container).textContent).not.toContain('adminSystemSettings.regional.title')

        const invalid = await render('/admin/system-settings?tab=bogus')
        expect(tab(invalid, 'regional').hasAttribute('data-active')).toBe(true)
        expect(activePanel(invalid).textContent).toContain('adminSystemSettings.regional.title')
    })
})
