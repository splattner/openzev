import { act, createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SourcePane } from '../src/features/supplementary/SourceDialog'
import type { SupplementarySource } from '../src/types/api'
import { renderWithProviders } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

// The real "more actions" menu is used here: this is the one place that opens it.
vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key}${JSON.stringify(options)}` : key) }),
}))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ isImpersonating: false }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: actual.DEFAULT_APP_SETTINGS, isLoading: false }) }
})
vi.mock('../src/lib/api/supplementary', () => ({}))

const source: SupplementarySource = {
    id: 'src-1', zev: 'zev-1', target: 'metering_point', held_by: 'participant', metering_point: 'mp-1', metering_point_meter_id: 'CH-100',
    participant: 'p-1', participant_name: 'Pia Muster', provides_history: true, provides_live: true, provides_forecast: false,
    live_last_seen_at: '2026-07-03T10:00:00Z', live_state: 'fresh', provider: 'solar_manager', label: 'Dach', external_id: 'ABC123', enabled: true, status: 'ok',
    consented_at: '2026-07-01T00:00:00Z', last_sync_at: '2026-07-03T10:00:00Z', last_success_at: '2026-07-03T10:00:00Z', last_error: '',
    synced_through: '2026-07-03T10:00:00Z', covers_from: '2026-07-01T00:00:00Z',
    reconciliation: { state: 'ok', days_compared: 7, export_deviation_pct: 1.2, import_deviation_pct: 0.4, best_shift_intervals: 0 },
    has_credential: true, push_token_prefix: null, push_token_created_at: null, push_token_last_used_at: null,
    created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-03T10:00:00Z',
} as SupplementarySource

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

describe('SourcePane', () => {
    const mount = () => renderWithProviders(
        createElement(SourcePane, { subject: 'CH-100', source, confirm: vi.fn(), canManage: true, eligible: { history: true, live: true }, onClose: vi.fn() }),
        cleanups,
    )

    it('names the source and what it provides in its header, in the same chrome as the tariff pane', async () => {
        const { container } = await mount()

        expect(container.querySelector('.detail-pane-header--brand h2')!.textContent).toBe('supplementary.provider.solar_manager · Dach')
        expect(container.querySelector('.detail-pane-meta')!.textContent).toBe('CH-100 · supplementary.capability.history, supplementary.capability.live')
    })

    it('has one block per capability and says nothing about a source that works', async () => {
        const { container } = await mount()

        expect(Array.from(container.querySelectorAll('.source-section h3')).map((h) => h.textContent)).toEqual([
            'supplementary.capability.history', 'supplementary.capability.live',
        ])
        expect(container.querySelector('.badge')).toBeNull()
        expect(container.querySelector('.issue-text')).toBeNull()
        // The id is plain text among the technical details, not code.
        const dd = Array.from(container.querySelectorAll('dd')).find((el) => el.textContent === 'ABC123')!
        expect(dd.querySelector('code')).toBeNull()
        expect(container.querySelector('details')!.querySelector('summary')!.textContent).toBe('supplementary.source.technical')
    })

    it('opens the menu with its actions in sections, the destructive ones in the last', async () => {
        const { container } = await mount()
        const trigger = container.querySelector<HTMLButtonElement>('button[aria-haspopup="menu"]')!
        expect(trigger.getAttribute('aria-label')).toBe('supplementary.source.moreActions')

        await act(async () => { trigger.click() })
        await waitForCondition(() => document.querySelector('[role="menuitem"]') !== null, 'the menu')
        const labels = Array.from(document.querySelectorAll('.mantine-Menu-label')).map((el) => el.textContent)
        expect(labels).toEqual(['supplementary.source.menu.connection', 'supplementary.source.menu.data', 'supplementary.source.menu.end'])
        const items = Array.from(document.querySelectorAll('[role="menuitem"]'))
        expect(items.at(-1)!.textContent).toBe('supplementary.actions.remove')
        expect(items.at(-1)!.className).toContain('action-menu-item-danger')
        expect(items.at(-2)!.className).toContain('action-menu-item-danger')
    })
})
