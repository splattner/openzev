import { AxiosError } from 'axios'
import { act, createElement, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ConnectionPointCard, PointLiveDialog } from '../src/features/meteringPoints/LiveSetup'
import { PushTokenPanel } from '../src/features/supplementary/PushTokenPanel'
import { SupplementarySourceModal, type ConnectHolder } from '../src/features/supplementary/SupplementarySourceModal'
import type { MeteringPoint, SupplementarySource } from '../src/types/api'
import { renderWithProviders } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key}${JSON.stringify(options)}` : key) }),
}))
const auth = vi.hoisted(() => ({ isImpersonating: false }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => auth }))
const pushToast = vi.fn()
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: actual.DEFAULT_APP_SETTINGS, isLoading: false }) }
})
vi.mock('../src/lib/clipboard', () => ({ copyToClipboard: vi.fn().mockResolvedValue(true) }))

const api = vi.hoisted(() => ({
    createSupplementarySource: vi.fn(),
    updateSupplementarySource: vi.fn(),
    deleteSupplementarySource: vi.fn(),
    disconnectSupplementarySource: vi.fn(),
    rotateSupplementaryPushToken: vi.fn(),
    revokeSupplementaryPushToken: vi.fn(),
}))
vi.mock('../src/lib/api/supplementary', () => api)

const source = (overrides: Partial<SupplementarySource> = {}): SupplementarySource => ({
    id: 'src-1', zev: 'zev-1', target: 'metering_point', held_by: 'participant', metering_point: 'mp-1', metering_point_meter_id: 'CH-100',
    participant: 'p-1', participant_name: 'Pia Muster', provides_history: true, provides_live: false, provides_forecast: false,
    live_last_seen_at: null, live_state: null, provider: 'push', label: '', external_id: '', enabled: true, status: 'ok',
    consented_at: '2026-07-01T00:00:00Z', last_sync_at: null, last_success_at: null, last_error: '', synced_through: null, covers_from: null,
    reconciliation: {}, has_credential: false, push_token_prefix: 'abcd', push_token_created_at: null, push_token_last_used_at: null,
    created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-01T00:00:00Z', ...overrides,
})
const liveOnly = (overrides: Partial<SupplementarySource> = {}) =>
    source({ id: 'src-live', provides_history: false, provides_live: true, live_state: 'fresh', live_last_seen_at: '2026-07-03T10:00:00Z', ...overrides })

const apiError = (data: Record<string, unknown>) =>
    new AxiosError('Bad Request', '400', undefined, undefined, { status: 400, data, statusText: 'Bad Request', headers: {}, config: {} as never })

const cleanups: Array<() => void> = []
beforeEach(() => {
    vi.clearAllMocks()
    auth.isImpersonating = false
})
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const buttons = (root: ParentNode) => Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
const buttonWith = (root: ParentNode, label: string) => buttons(root).find((b) => b.textContent?.includes(label))
const dialogs = () => Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]'))
const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]')
async function click(element: HTMLElement) {
    await act(async () => { element.click() })
}

describe('SupplementarySourceModal for live data', () => {
    const point = { metering_point: 'mp-1', meter_id: 'CH-100', zev: 'zev-1' }
    async function open(holder: ConnectHolder, props: Record<string, unknown> = { point, available: ['live'] }) {
        api.createSupplementarySource.mockResolvedValue({ ...liveOnly(), push_token: 'ozs_abcd_secret' })
        await renderWithProviders(createElement(SupplementarySourceModal, { holder, onClose: vi.fn(), ...props }), cleanups)
        return dialog()!
    }
    const submit = async (modal: HTMLElement) => {
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
        await act(async () => { buttonWith(modal, 'supplementary.modal.connect')!.click() })
    }

    it('connects live data for a holder as a push source without history, never forecast', async () => {
        const modal = await open('participant')
        // Live is push only: nothing to choose, no credentials.
        expect(modal.querySelectorAll('input[type="radio"]')).toHaveLength(1)
        expect(modal.textContent).not.toContain('supplementary.provider.solar_manager')
        expect(modal.querySelector('input[type="password"]')).toBeNull()
        expect(modal.textContent).toContain('supplementary.consent.liveVisible')
        expect(modal.textContent).toContain('supplementary.consent.liveNotBilling')
        expect(modal.textContent).not.toContain('supplementary.consent.stored')
        expect(modal.textContent).not.toContain('supplementary.consent.zevHeld')
        await submit(modal)

        const payload = api.createSupplementarySource.mock.calls[0][0]
        expect(payload).toMatchObject({
            metering_point: 'mp-1', provider: 'push', target: 'metering_point', held_by: 'participant',
            provides_history: false, provides_live: true, consent: true,
        })
        expect(payload).not.toHaveProperty('provides_forecast')
        await waitForCondition(() => document.querySelector('[data-testid="live-endpoint"]') !== null, 'the live endpoint on the token screen')
        expect(document.querySelector('[data-testid="push-token"]')!.textContent).toContain('ozs_abcd_secret')
        expect(dialog()!.textContent).not.toContain('supplementary.push.columns')
    })

    it('connects a ZEV-operated meter with the ZEV-held confirmation', async () => {
        const modal = await open('zev', { point })
        expect(modal.textContent).toContain('supplementary.consent.zevHeld')
        expect(modal.querySelectorAll('input[type="radio"]')).toHaveLength(0)
        expect(modal.textContent).not.toContain('supplementary.consent.liveVisible')
        expect(modal.textContent).not.toContain('supplementary.consent.connectionPoint')
        await submit(modal)

        expect(api.createSupplementarySource.mock.calls[0][0]).toMatchObject({
            metering_point: 'mp-1', target: 'metering_point', held_by: 'zev', zev: 'zev-1', provider: 'push', provides_history: false, provides_live: true, consent: true,
        })
    })

    it('connects the grid connection point without a metering point', async () => {
        const modal = await open('connection-point', { zevId: 'zev-1' })
        expect(modal.textContent).toContain('supplementary.consent.zevHeld')
        expect(modal.textContent).toContain('supplementary.consent.connectionPoint')
        await submit(modal)

        const payload = api.createSupplementarySource.mock.calls[0][0]
        expect(payload).toMatchObject({ target: 'connection_point', held_by: 'zev', zev: 'zev-1', provides_history: false, provides_live: true })
        expect(payload.metering_point).toBeUndefined()
    })

    it('cannot connect before consent is given', async () => {
        const modal = await open('participant')
        expect(buttonWith(modal, 'supplementary.modal.connect')!.disabled).toBe(true)
    })

    it('shows a refused capability or holder as a banner', async () => {
        const modal = await open('participant')
        api.createSupplementarySource.mockRejectedValue(apiError({ provides_live: ['Live is not available for this source yet.'], held_by: ['Not allowed.'] }))
        await submit(modal)
        await waitForCondition(() => (dialog()?.textContent ?? '').includes('Live is not available'), 'the field error')

        expect(dialog()!.querySelector('[role="alert"]')!.textContent).toContain('Not allowed.')
    })

    it('shows a consent error next to the checkbox', async () => {
        const modal = await open('participant')
        api.createSupplementarySource.mockRejectedValue(apiError({ consent: ['Consent is required.'] }))
        await submit(modal)
        await waitForCondition(() => (dialog()?.textContent ?? '').includes('Consent is required.'), 'the consent error')

        expect(dialog()!.querySelector('.field-error')!.textContent).toBe('Consent is required.')
    })
})

describe('PushTokenPanel', () => {
    it('shows the live endpoint, an example and the sign convention for a live source', async () => {
        await renderWithProviders(createElement(PushTokenPanel, { token: 'ozs_x', onDismiss: vi.fn(), capabilities: { history: false, live: true } }), cleanups)

        const live = document.querySelector('[data-testid="live-endpoint"]')!
        expect(live.textContent).toContain('/metering/live/ingest/')
        expect(document.body.textContent).toContain('"meter_power_w"')
        expect(document.body.textContent).toContain('supplementary.push.liveSignHint')
        expect(document.body.textContent).not.toContain('/metering/supplementary/ingest/')
        expect(document.body.textContent).not.toContain('supplementary.push.columns')
    })

    it('keeps the CSV endpoint and columns for a history source, and shows both for a source with both', async () => {
        const first = await renderWithProviders(createElement(PushTokenPanel, { token: 'ozs_x', onDismiss: vi.fn() }), cleanups)
        expect(first.container.textContent).toContain('/metering/supplementary/ingest/')
        expect(first.container.textContent).toContain('supplementary.push.columns')
        expect(first.container.querySelector('[data-testid="live-endpoint"]')).toBeNull()

        const both = await renderWithProviders(createElement(PushTokenPanel, { token: 'ozs_x', onDismiss: vi.fn(), capabilities: { history: true, live: true } }), cleanups)
        expect(both.container.textContent).toContain('/metering/supplementary/ingest/')
        expect(both.container.querySelector('[data-testid="live-endpoint"]')).not.toBeNull()
    })
})

describe('ConnectionPointCard', () => {
    const setup = (options: { liveOn?: boolean; available?: boolean; sourceId?: string | null; sources?: SupplementarySource[] }) => ({
        liveOn: options.liveOn ?? true,
        sourcesQuery: { data: options.sources ?? [], isError: false, isFetching: false, refetch: vi.fn() },
        zevEligibleQuery: {
            data: options.available === undefined && options.sourceId === undefined
                ? undefined
                : { zev: 'zev-1', metering_points: [], connection_point: { available: options.available ?? false, source: options.sourceId ?? null } },
        },
        zevEligibleByPoint: new Map(),
    }) as never
    const connection = (overrides: Partial<SupplementarySource> = {}) =>
        liveOnly({ id: 'src-cp', target: 'connection_point', held_by: 'zev', metering_point: null, metering_point_meter_id: null, participant: null, participant_name: null, ...overrides })
    const mountCard = (state: ReturnType<typeof setup>, canWrite: boolean) =>
        renderWithProviders(createElement(ConnectionPointCard, { zevId: 'zev-1', setup: state, canWrite, confirm: vi.fn() }), cleanups)

    it('offers a manager of a physical ZEV to connect the grid connection point', async () => {
        const { container } = await mountCard(setup({ available: true }), true)

        expect(container.textContent).toContain('supplementary.connection.notConnected')
        await click(buttonWith(container, 'supplementary.connection.connect')!)
        expect(dialog()!.textContent).toContain('supplementary.consent.connectionPoint')
    })

    it('hides the card where the ZEV cannot have a connection point (virtual ZEV: not available, no source)', async () => {
        const { container } = await mountCard(setup({ available: false, sourceId: null }), true)

        expect(container.querySelector('section')).toBeNull()
    })

    it('hides the card while the live flag is off', async () => {
        const { container } = await mountCard(setup({ liveOn: false, available: true }), true)

        expect(container.querySelector('section')).toBeNull()
    })

    it('shows a manager the connected source with its actions', async () => {
        const { container } = await mountCard(setup({ available: false, sourceId: 'src-cp', sources: [connection()] }), true)

        expect(container.textContent).toContain('live.state.fresh')
        expect(buttonWith(container, 'supplementary.connection.connect')).toBeUndefined()
        expect(buttonWith(container, 'supplementary.actions.rotate')).toBeUndefined()

        // The details and every action are in the source dialog.
        await click(buttonWith(container, 'supplementary.connection.details')!)
        expect(dialog()!.textContent).toContain('supplementary.source.title{"subject":"supplementary.connection.title"}')
        expect(buttonWith(dialog()!, 'supplementary.actions.rotate')).toBeDefined()
        expect(buttonWith(dialog()!, 'supplementary.actions.remove')).toBeDefined()
    })

    it('shows a viewer the state only, and nothing when there is no source', async () => {
        const withSource = await mountCard(setup({ sources: [connection()] }), false)
        expect(withSource.container.textContent).toContain('live.state.fresh')
        expect(buttons(withSource.container)).toHaveLength(0)

        const none = await mountCard(setup({ sources: [] }), false)
        expect(none.container.querySelector('section')).toBeNull()
    })

    it('does not offer a viewer to connect even when the ZEV could have one', async () => {
        const { container } = await mountCard(setup({ available: true }), false)

        expect(container.querySelector('section')).toBeNull()
    })
})

describe('PointLiveDialog', () => {
    const mp = { id: 'mp-1', zev: 'zev-1', meter_id: 'CH-100' } as MeteringPoint
    const zevSource = (overrides: Partial<SupplementarySource> = {}) => liveOnly({ id: 'src-live', held_by: 'zev', participant: null, participant_name: null, ...overrides })
    const setupWith = (live: string | null, sources: SupplementarySource[] = []) => ({
        sourcesQuery: { data: sources, isLoading: false, isError: false, refetch: vi.fn() },
        zevEligibleByPoint: new Map([['mp-1', { sources: { history: null, live, forecast: null } }]]),
    }) as never

    it('opens the connect flow for a point without a live source and keeps it once the source exists', async () => {
        function Host() {
            const [live, setLive] = useState<string | null>(null)
            return createElement('div', null,
                createElement('button', { 'data-testid': 'source-created', onClick: () => setLive('src-live') }),
                createElement(PointLiveDialog, { point: mp, setup: setupWith(live, live ? [zevSource()] : []), confirm: vi.fn(), onClose: vi.fn() }))
        }
        await renderWithProviders(createElement(Host), cleanups)
        expect(dialog()!.textContent).toContain('supplementary.consent.zevHeld')

        // The create succeeded and the lists refetched: the one-time token dialog must not turn into the rows.
        await click(document.querySelector<HTMLElement>('[data-testid="source-created"]')!)
        expect(dialog()!.textContent).toContain('supplementary.consent.zevHeld')
    })

    it('keeps the new source\'s token on screen while the lists refetch', async () => {
        api.createSupplementarySource.mockResolvedValue({ ...zevSource(), push_token: 'ozs_abcd_secret' })
        function Host() {
            const [live, setLive] = useState<string | null>(null)
            return createElement('div', null,
                createElement('button', { 'data-testid': 'source-created', onClick: () => setLive('src-live') }),
                createElement(PointLiveDialog, { point: mp, setup: setupWith(live, live ? [zevSource()] : []), confirm: vi.fn(), onClose: vi.fn() }))
        }
        await renderWithProviders(createElement(Host), cleanups)
        await click(dialog()!.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
        await act(async () => { buttonWith(dialog()!, 'supplementary.modal.connect')!.click() })
        await waitForCondition(() => document.querySelector('[data-testid="push-token"]') !== null, 'the token')
        await click(document.querySelector<HTMLElement>('[data-testid="source-created"]')!)

        expect(document.querySelector('[data-testid="push-token"]')!.textContent).toContain('ozs_abcd_secret')
        expect(dialogs()).toHaveLength(1)
    })

    it('opens a live row for a point that already has a live source, and no history row', async () => {
        await renderWithProviders(createElement(PointLiveDialog, { point: mp, setup: setupWith('src-live', [zevSource()]), confirm: vi.fn(), onClose: vi.fn() }), cleanups)

        expect(dialog()!.textContent).toContain('supplementary.live.dialogTitle')
        expect(dialog()!.textContent).not.toContain('supplementary.consent.zevHeld')
        const rows = dialog()!.querySelectorAll('li')
        expect(Array.from(rows).map((li) => li.dataset.capability)).toEqual(['live'])
        expect(rows[0].textContent).toContain('live.state.fresh')
    })

    it('shows the source\'s details and actions from its row, in the same dialog, and goes back', async () => {
        await renderWithProviders(createElement(PointLiveDialog, { point: mp, setup: setupWith('src-live', [zevSource()]), confirm: vi.fn(), onClose: vi.fn() }), cleanups)
        await click(dialog()!.querySelector('li button')!)

        expect(dialogs()).toHaveLength(1)
        expect(dialog()!.textContent).toContain('supplementary.source.title')
        expect(buttonWith(dialog()!, 'supplementary.actions.rotate')).toBeDefined()
        expect(buttonWith(dialog()!, 'supplementary.actions.remove')).toBeDefined()
        expect(buttonWith(dialog()!, 'supplementary.live.alsoSend')).toBeUndefined()
        await click(buttonWith(dialog()!, 'supplementary.modal.back')!)
        expect(dialog()!.querySelector('li')).not.toBeNull()
    })
})
