import { act, createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MyConnections } from '../src/features/supplementary/MyConnections'
import type { EligibleMeteringPoint, SupplementarySource } from '../src/types/api'
import { renderWithProviders } from './helpers/render'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key}${JSON.stringify(options)}` : key) }),
}))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ isImpersonating: false }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: actual.DEFAULT_APP_SETTINGS, isLoading: false }) }
})
// The dialog has its own tests; here only that it opens for the right source.
vi.mock('../src/features/supplementary/SourceDialog', () => ({
    SourceDialog: ({ source, subject, eligible }: { source: SupplementarySource; subject: string; eligible?: Record<string, boolean> }) =>
        createElement('div', { 'data-testid': 'dialog', 'data-eligible': JSON.stringify(eligible) }, `${source.id}:${subject}`),
}))

const held: EligibleMeteringPoint[] = [
    { metering_point: 'mp-1', meter_id: 'CH-100', zev: 'zev-1', zev_name: 'Sonnenhof', participant: 'p-1', source: null, eligible_capabilities: ['history', 'live', 'forecast'] },
]

const source = (overrides: Partial<SupplementarySource> = {}): SupplementarySource => ({
    id: 'src-1', zev: 'zev-1', target: 'metering_point', held_by: 'participant', metering_point: 'mp-1', metering_point_meter_id: 'CH-100',
    participant: 'p-1', participant_name: 'Pia Muster', provides_history: true, provides_live: true, provides_forecast: false,
    live_last_seen_at: '2026-07-03T10:00:00Z', live_state: 'fresh', provider: 'push', label: 'Dach', external_id: '', enabled: true, status: 'ok',
    consented_at: '2026-07-01T00:00:00Z', last_sync_at: null, last_success_at: null, last_error: '', synced_through: null, covers_from: null,
    reconciliation: {}, has_credential: false, push_token_prefix: 'abcd', push_token_created_at: null, push_token_last_used_at: null,
    created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-03T10:00:00Z',
    ...overrides,
})

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const mount = (sources: SupplementarySource[]) =>
    renderWithProviders(createElement(MyConnections, { sources, held, confirm: vi.fn() }), cleanups)

describe('MyConnections', () => {
    it('lists only the participant-held sources on meters the user holds', async () => {
        const { container } = await mount([
            source(),
            source({ id: 'zev-held', held_by: 'zev', participant: null }),
            source({ id: 'other-meter', metering_point: 'mp-9', metering_point_meter_id: 'CH-900' }),
            source({ id: 'grid', target: 'connection_point', held_by: 'zev', metering_point: null, metering_point_meter_id: null }),
        ])

        const rows = container.querySelectorAll('li[data-source]')
        expect(rows).toHaveLength(1)
        expect(rows[0].getAttribute('data-source')).toBe('src-1')
        expect(rows[0].textContent).toContain('supplementary.provider.push · Dach')
        expect(rows[0].textContent).toContain('CH-100')
        expect(container.textContent).not.toContain('CH-900')
    })

    it('shows a chip and a status for each capability the source provides', async () => {
        const { container } = await mount([source()])
        const row = container.querySelector('li[data-source]')!

        expect(row.textContent).toContain('supplementary.capability.history')
        expect(row.textContent).toContain('supplementary.capability.live')
        expect(row.textContent).toContain('live.state.fresh')
        expect(row.querySelectorAll('.badge')).toHaveLength(4)
    })

    it('leaves the live chip out of a history-only source', async () => {
        const { container } = await mount([source({ provides_live: false, live_state: null })])
        const row = container.querySelector('li[data-source]')!

        expect(row.textContent).toContain('supplementary.capability.history')
        expect(row.textContent).not.toContain('supplementary.capability.live')
    })

    it('opens the source dialog for the chosen source', async () => {
        const { container } = await mount([source()])
        expect(container.querySelector('[data-testid="dialog"]')).toBeNull()

        await act(async () => {
            container.querySelector<HTMLButtonElement>('li[data-source] button')!.click()
        })

        expect(container.querySelector('[data-testid="dialog"]')!.textContent).toBe('src-1:CH-100')
    })

    it('passes what the meter can still offer, forecast included, to the source dialog', async () => {
        const { container } = await mount([source({ provider: 'solar_manager' })])
        await act(async () => {
            container.querySelector<HTMLButtonElement>('li[data-source] button')!.click()
        })
        expect(JSON.parse(container.querySelector('[data-testid="dialog"]')!.getAttribute('data-eligible')!)).toEqual({
            history: true, live: true, forecast: true,
        })
    })

    it('shows a forecast chip, with its own status only when the source has no history', async () => {
        const both = await mount([source({ provides_forecast: true })])
        const row = both.container.querySelector('li[data-source]')!
        expect(row.textContent).toContain('supplementary.capability.forecast')
        expect(row.querySelectorAll('.badge')).toHaveLength(5)
        cleanups.splice(0).forEach((cleanup) => cleanup())

        const only = await mount([source({ provides_history: false, provides_live: false, live_state: null, provides_forecast: true, provider: 'forecast_solar' })])
        expect(only.container.querySelector('li[data-source]')!.querySelectorAll('.badge')).toHaveLength(2)
    })

    it('explains where connections appear while there are none', async () => {
        const { container } = await mount([source({ held_by: 'zev', participant: null })])

        expect(container.querySelector('li[data-source]')).toBeNull()
        expect(container.textContent).toContain('pages.myMeteringPoints.connections.empty')
        expect(container.querySelector('button')).toBeNull()
    })
})
