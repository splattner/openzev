import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { AdminSystemSettingsPage } from '../src/pages/AdminSystemSettingsPage'

const flagApi = vi.hoisted(() => ({ fetchFeatureFlags: vi.fn(), updateFeatureFlag: vi.fn() }))

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options?.variable ? `${key}:${options.variable}` : key) }),
}))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/api/auth', () => ({
    createOAuthProviderConfig: vi.fn(),
    deleteOAuthProviderConfig: vi.fn(),
    fetchFeatureFlags: flagApi.fetchFeatureFlags,
    fetchOAuthProviderConfigs: vi.fn().mockResolvedValue([]),
    fetchSystemHealth: vi.fn().mockResolvedValue({ mfa: { status: 'ok', encryption_key_configured: true } }),
    updateAppSettings: vi.fn(),
    updateFeatureFlag: flagApi.updateFeatureFlag,
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
                mfa_required: false,
                mfa_grace_period_days: 14,
                updated_at: '2026-01-01T00:00:00Z',
            },
            isLoading: false,
        }),
    }
})
vi.mock('../src/features/settings/VatSettingsSection', () => ({
    VatSettingsSection: () => createElement('section', null, 'vat-stub'),
}))
vi.mock('../src/features/backups/BackupSettingsSection', () => ({
    BackupSettingsSection: () => createElement('section', null, 'backup-stub'),
}))

function RoutedPage() {
    const location = useLocation()
    return createElement('div', null,
        createElement('output', null, location.pathname + location.search + location.hash),
        createElement(AdminSystemSettingsPage),
    )
}

const cleanups: (() => void)[] = []
let lastClient: QueryClient
beforeEach(() => flagApi.fetchFeatureFlags.mockResolvedValue([]))
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function render(url: string) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    lastClient = client
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
        expect(tabs).toHaveLength(6)
        for (const tabElement of Array.from(tabs)) {
            expect(tabElement.classList.contains('app-tabs-tab')).toBe(true)
            const panel = container.querySelector(`#${tabElement.getAttribute('aria-controls')}`)
            expect(panel?.getAttribute('role')).toBe('tabpanel')
        }
        // Inactive panels render as empty shells (Mantine hides panel content
        // for inactive tabs in the test env); only the active panel has content.
        expect(container.querySelectorAll('[role="tabpanel"]')).toHaveLength(6)
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

    it('opens the backup tab from its URL and renders its section', async () => {
        const container = await render('/admin/system-settings?tab=backup')
        expect(tab(container, 'backup').hasAttribute('data-active')).toBe(true)
        expect(activePanel(container).textContent).toContain('backup-stub')
    })

    it('retains unrelated parameters and hash when changing tabs or returning to the default', async () => {
        const container = await render('/admin/system-settings?tab=backup&source=bookmark#settings')
        await act(async () => tab(container, 'security').click())
        expect(container.querySelector('output')?.textContent).toBe('/admin/system-settings?tab=security&source=bookmark#settings')
        await act(async () => tab(container, 'regional').click())
        expect(container.querySelector('output')?.textContent).toBe('/admin/system-settings?source=bookmark#settings')
    })
})

describe('the Functions tab', () => {
    const flag = (overrides: Record<string, unknown> = {}) => ({
        id: 1, name: 'supplementary_energy_data_enabled', description: 'Energy data', enabled: true,
        follows_default: false, controlled_by_env: false, updated_at: '2026-10-12T00:00:00Z', ...overrides,
    })
    const switchOf = (container: Element) => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!

    async function renderFeatures(flags: unknown[]) {
        flagApi.fetchFeatureFlags.mockResolvedValue(flags)
        const container = await render('/admin/system-settings?tab=features')
        for (let i = 0; i < 20 && !container.querySelector('input[type="checkbox"]'); i++) {
            await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)) })
        }
        return container
    }

    it('says that a flag follows the instance default, and leaves the switch usable', async () => {
        const container = await renderFeatures([flag({ follows_default: true })])

        expect(container.textContent).toContain('features.followsDefault')
        expect(container.textContent).not.toContain('features.controlledByEnv')
        expect(switchOf(container).disabled).toBe(false)
    })

    it('explains a flag the server environment decides, and does not offer a switch that has no effect', async () => {
        const container = await renderFeatures([flag({ follows_default: true, controlled_by_env: true })])

        expect(container.textContent).toContain('features.controlledByEnv:FEATURE_SUPPLEMENTARY_ENERGY_DATA_ENABLED')
        expect(container.textContent).not.toContain('features.followsDefault')
        expect(switchOf(container).disabled).toBe(true)
    })

    it('refreshes what depends on a flag after it is toggled: health, eligibility, sources and meters', async () => {
        flagApi.updateFeatureFlag.mockResolvedValue(flag({ enabled: false }))
        const container = await renderFeatures([flag()])
        const invalidate = vi.spyOn(lastClient, 'invalidateQueries')

        await act(async () => { switchOf(container).click() })
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)) })

        const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey))
        for (const expected of [
            ['auth', 'feature-flags'], ['auth', 'system-health'], ['metering', 'supplementary-eligible'],
            ['metering', 'supplementary-sources'], ['metering', 'points'],
        ]) {
            expect(keys, expected.join('/')).toContain(JSON.stringify(expected))
        }
    })
})
