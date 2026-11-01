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

// The overview is for telling several connections apart; a second one on another held meter makes it appear.
const second = (overrides: Partial<SupplementarySource> = {}) =>
    source({ id: 'src-2', metering_point: 'mp-2', metering_point_meter_id: 'CH-200', ...overrides })
const held2: EligibleMeteringPoint[] = [...held, { ...held[0], metering_point: 'mp-2', meter_id: 'CH-200' }]

const mount = (sources: SupplementarySource[]) =>
    renderWithProviders(createElement(MyConnections, { sources, held: held2, confirm: vi.fn() }), cleanups)

describe('MyConnections', () => {
    it('lists only the participant-held sources on meters the user holds', async () => {
        const { container } = await mount([
            source(),
            second(),
            source({ id: 'zev-held', held_by: 'zev', participant: null }),
            source({ id: 'other-meter', metering_point: 'mp-9', metering_point_meter_id: 'CH-900' }),
            source({ id: 'grid', target: 'connection_point', held_by: 'zev', metering_point: null, metering_point_meter_id: null }),
        ])

        const rows = container.querySelectorAll('li[data-source]')
        expect(rows).toHaveLength(2)
        expect(rows[0].getAttribute('data-source')).toBe('src-1')
        expect(rows[0].textContent).toContain('supplementary.provider.push · Dach')
        expect(rows[0].textContent).toContain('CH-100')
        expect(container.textContent).not.toContain('CH-900')
    })

    it('shows nothing for one connection or none: the meter card below already says it all', async () => {
        expect((await mount([source()])).container.querySelector('section')).toBeNull()
        cleanups.splice(0).forEach((cleanup) => cleanup())
        expect((await mount([])).container.querySelector('section')).toBeNull()
        cleanups.splice(0).forEach((cleanup) => cleanup())
        expect((await mount([source({ held_by: 'zev', participant: null })])).container.querySelector('section')).toBeNull()
    })

    it('shows a quiet chip for each capability the source provides and no status while it works', async () => {
        const { container } = await mount([source(), second()])
        const row = container.querySelector('li[data-source="src-1"]')!

        expect(row.textContent).toContain('supplementary.capability.history')
        expect(row.textContent).toContain('supplementary.capability.live')
        expect(row.querySelectorAll('.badge')).toHaveLength(2)
        expect(row.querySelectorAll('.badge-tag')).toHaveLength(2)
        expect(row.textContent).not.toContain('live.state.fresh')
        expect(row.textContent).not.toContain('supplementary.status.ok')
        expect(row.querySelector('.issue-text')).toBeNull()
    })

    it('names a problem next to the capability it concerns, once', async () => {
        const { container } = await mount([source({ live_state: 'stale' }), second({ status: 'reconnect_required', provides_live: false, live_state: null })])

        const stale = container.querySelector('li[data-source="src-1"]')!
        expect(stale.querySelectorAll('.issue-text--warning')).toHaveLength(1)
        expect(stale.querySelector('[class~="connection-capability"]:nth-of-type(2)')?.textContent).toContain('live.state.stale')
        const reconnect = container.querySelector('li[data-source="src-2"]')!
        expect(reconnect.querySelectorAll('.issue-text--error')).toHaveLength(1)
        expect(reconnect.textContent).toContain('supplementary.status.reconnect_required')
    })

    it('leaves the live chip out of a history-only source', async () => {
        const { container } = await mount([source({ provides_live: false, live_state: null }), second()])
        const row = container.querySelector('li[data-source="src-1"]')!

        expect(row.textContent).toContain('supplementary.capability.history')
        expect(row.textContent).not.toContain('supplementary.capability.live')
    })

    it('opens the source dialog for the chosen source', async () => {
        const { container } = await mount([source(), second()])
        expect(container.querySelector('[data-testid="dialog"]')).toBeNull()

        await act(async () => {
            container.querySelector<HTMLButtonElement>('li[data-source="src-1"] button')!.click()
        })

        expect(container.querySelector('[data-testid="dialog"]')!.textContent).toBe('src-1:CH-100')
    })

    it('passes what the meter can still offer, forecast included, to the source dialog', async () => {
        const { container } = await mount([source({ provider: 'solar_manager' }), second()])
        await act(async () => {
            container.querySelector<HTMLButtonElement>('li[data-source="src-1"] button')!.click()
        })
        expect(JSON.parse(container.querySelector('[data-testid="dialog"]')!.getAttribute('data-eligible')!)).toEqual({
            history: true, live: true, forecast: true,
        })
    })

    it('shows a forecast chip for a source that provides the forecast', async () => {
        const { container } = await mount([source({ provides_forecast: true }), second()])
        expect(container.querySelector('li[data-source="src-1"]')!.textContent).toContain('supplementary.capability.forecast')
    })
})
