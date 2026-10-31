import { AxiosError } from 'axios'
import { act, createElement, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ConfirmDialog, useConfirmDialog } from '../src/components/ConfirmDialog'
import { ConnectionPointCard, PointLiveDialog } from '../src/features/meteringPoints/LiveSetup'
import { LiveSourceSection } from '../src/features/supplementary/LiveSourceSection'
import { PushTokenPanel } from '../src/features/supplementary/PushTokenPanel'
import { SupplementarySourceModal, type SourceModalMode } from '../src/features/supplementary/SupplementarySourceModal'
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
const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]')
async function click(element: HTMLElement) {
    await act(async () => { element.click() })
}

describe('SupplementarySourceModal capabilities', () => {
    const point = { metering_point: 'mp-1', meter_id: 'CH-100', zev: 'zev-1' }
    async function open(mode: SourceModalMode, props: Record<string, unknown> = { point }) {
        api.createSupplementarySource.mockResolvedValue({ ...liveOnly(), push_token: 'ozs_abcd_secret' })
        await renderWithProviders(createElement(SupplementarySourceModal, { mode, onClose: vi.fn(), ...props }), cleanups)
        return dialog()!
    }
    const submit = async (modal: HTMLElement) => {
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
        await act(async () => { buttonWith(modal, 'supplementary.modal.connect')!.click() })
    }

    it('keeps the history connect as it was: provider choice, no capability fields', async () => {
        const modal = await open('history')
        expect(modal.querySelectorAll('input[type="radio"]')).toHaveLength(2)
        expect(modal.textContent).toContain('supplementary.consent.stored')
        await click(modal.querySelectorAll<HTMLInputElement>('input[type="radio"]')[1])
        await submit(modal)

        expect(api.createSupplementarySource).toHaveBeenCalledWith({
            metering_point: 'mp-1', provider: 'push', label: undefined, external_id: undefined, api_key: undefined, consent: true,
        })
    })

    it('connects live data for a holder as a push source without history, never forecast', async () => {
        const modal = await open('live')
        expect(modal.querySelectorAll('input[type="radio"]')).toHaveLength(0)
        expect(modal.querySelector('input[type="password"]')).toBeNull()
        expect(modal.textContent).toContain('supplementary.consent.liveVisible')
        expect(modal.textContent).toContain('supplementary.consent.liveNotBilling')
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
        const modal = await open('zev-live')
        expect(modal.textContent).toContain('supplementary.consent.zevHeld')
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
        const modal = await open('live')
        expect(buttonWith(modal, 'supplementary.modal.connect')!.disabled).toBe(true)
    })

    it('shows a refused capability or holder as a banner', async () => {
        const modal = await open('live')
        api.createSupplementarySource.mockRejectedValue(apiError({ provides_live: ['Live is not available for this source yet.'], held_by: ['Not allowed.'] }))
        await submit(modal)
        await waitForCondition(() => (dialog()?.textContent ?? '').includes('Live is not available'), 'the field error')

        expect(dialog()!.querySelector('[role="alert"]')!.textContent).toContain('Not allowed.')
    })

    it('shows a consent error next to the checkbox', async () => {
        const modal = await open('live')
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

function SectionHarness({ sources, heldBy = 'participant', bare = false }: { sources: SupplementarySource[]; heldBy?: 'participant' | 'zev'; bare?: boolean }) {
    const { dialog: confirmation, confirm, handleConfirm, handleCancel, isLoading } = useConfirmDialog()
    return createElement('div', null,
        createElement(LiveSourceSection, { meteringPointId: 'mp-1', meterId: 'CH-100', zevId: 'zev-1', zevName: 'Sonnenhof', heldBy, sources, confirm, bare }),
        confirmation && createElement(ConfirmDialog, { ...confirmation, isLoading, onConfirm: handleConfirm, onCancel: handleCancel }),
    )
}
const mountSection = (sources: SupplementarySource[], heldBy: 'participant' | 'zev' = 'participant', bare = false) =>
    renderWithProviders(createElement(SectionHarness, { sources, heldBy, bare }), cleanups)

describe('LiveSourceSection', () => {
    it('offers to connect live data when the point has no live source', async () => {
        const { container } = await mountSection([])

        expect(container.textContent).toContain('supplementary.live.notConnected')
        expect(buttonWith(container, 'supplementary.live.connect')!.className).toContain('button-primary')
        expect(buttonWith(container, 'supplementary.live.alsoSend')).toBeUndefined()
        await click(buttonWith(container, 'supplementary.live.connect')!)
        expect(dialog()!.textContent).toContain('supplementary.consent.liveVisible')
    })

    it('puts "also send live data" first when the history source is a push source, and confirms with the live consent', async () => {
        api.updateSupplementarySource.mockResolvedValue(source({ provides_live: true }))
        const { container } = await mountSection([source()])

        expect(buttonWith(container, 'supplementary.live.alsoSend')!.className).toContain('button-primary')
        expect(buttonWith(container, 'supplementary.live.connect')!.className).toContain('button-secondary')
        await click(buttonWith(container, 'supplementary.live.alsoSend')!)
        expect(dialog()!.textContent).toContain('supplementary.consent.liveVisible')
        await act(async () => { buttons(dialog()!).find((b) => b.textContent === 'supplementary.live.alsoSend')!.click() })

        expect(api.updateSupplementarySource).toHaveBeenCalledWith('src-1', { provides_live: true, consent: true })
    })

    it('does not offer to reuse a Solar Manager history source', async () => {
        const { container } = await mountSection([source({ provider: 'solar_manager' })])

        expect(buttonWith(container, 'supplementary.live.alsoSend')).toBeUndefined()
        expect(buttonWith(container, 'supplementary.live.connect')!.className).toContain('button-primary')
    })

    it('shows a separate live source with its state, token prefix and every action', async () => {
        const { container } = await mountSection([source({ provider: 'solar_manager', external_id: 'ABC' }), liveOnly()])

        expect(container.textContent).toContain('live.state.fresh')
        expect(container.textContent).toContain('ozs_abcd_')
        for (const label of ['supplementary.actions.rotate', 'supplementary.live.revoke', 'supplementary.actions.disconnect', 'supplementary.actions.remove']) {
            expect(buttonWith(container, label), label).toBeDefined()
        }
        expect(buttonWith(container, 'supplementary.live.stop')).toBeUndefined()
        expect(buttonWith(container, 'supplementary.live.connect')).toBeUndefined()
    })

    it('rotates the token of a separate live source and shows it once with the live endpoint', async () => {
        api.rotateSupplementaryPushToken.mockResolvedValue({ push_token: 'ozs_new_secret', push_token_prefix: 'new' })
        const { container } = await mountSection([liveOnly()])
        await click(buttonWith(container, 'supplementary.actions.rotate')!)
        await act(async () => { buttons(dialog()!).find((b) => b.textContent === 'supplementary.actions.rotate')!.click() })
        await waitForCondition(() => container.querySelector('[data-testid="push-token"]') !== null, 'the new token')

        expect(container.querySelector('[data-testid="push-token"]')!.textContent).toContain('ozs_new_secret')
        expect(container.querySelector('[data-testid="live-endpoint"]')).not.toBeNull()
    })

    it('cannot rotate or connect while impersonating', async () => {
        auth.isImpersonating = true
        const rotate = await mountSection([liveOnly()])
        expect(buttonWith(rotate.container, 'supplementary.actions.rotate')!.disabled).toBe(true)
        const connect = await mountSection([])
        expect(buttonWith(connect.container, 'supplementary.live.connect')!.disabled).toBe(true)
    })

    it('stops live data on a source shared with history instead of disconnecting it', async () => {
        api.updateSupplementarySource.mockResolvedValue(source())
        const { container } = await mountSection([source({ provides_live: true, live_state: 'stale' })])

        expect(container.textContent).toContain('live.state.stale')
        expect(container.querySelector('[data-testid="live-endpoint"]')).not.toBeNull()
        expect(buttonWith(container, 'supplementary.actions.disconnect')).toBeUndefined()
        expect(buttonWith(container, 'supplementary.actions.remove')).toBeUndefined()
        await click(buttonWith(container, 'supplementary.live.stop')!)
        await act(async () => { buttons(dialog()!).find((b) => b.textContent === 'supplementary.live.stop')!.click() })

        expect(api.updateSupplementarySource).toHaveBeenCalledWith('src-1', { provides_live: false })
    })

    it('offers no way to connect in a bare host, which is already a dialog', async () => {
        const { container } = await mountSection([], 'zev', true)

        expect(container.textContent).toContain('supplementary.live.zevNotConnected')
        expect(buttonWith(container, 'supplementary.live.connect')).toBeUndefined()
    })

    it('connects a ZEV-operated meter with held_by zev', async () => {
        const { container } = await mountSection([], 'zev')
        await click(buttonWith(container, 'supplementary.live.connect')!)

        expect(dialog()!.textContent).toContain('supplementary.consent.zevHeld')
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
        expect(buttonWith(container, 'supplementary.actions.rotate')).toBeDefined()
        expect(buttonWith(container, 'supplementary.actions.remove')).toBeDefined()
        expect(buttonWith(container, 'supplementary.connection.connect')).toBeUndefined()
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
    const setupWith = (live: string | null) => ({
        sourcesQuery: { data: [], isLoading: false, isError: false, refetch: vi.fn() },
        zevEligibleByPoint: new Map([['mp-1', { sources: { history: null, live, forecast: null } }]]),
    }) as never

    it('opens the connect dialog for a point without a live source and keeps it once the source exists', async () => {
        function Host() {
            const [live, setLive] = useState<string | null>(null)
            return createElement('div', null,
                createElement('button', { 'data-testid': 'source-created', onClick: () => setLive('src-live') }),
                createElement(PointLiveDialog, { point: mp, setup: setupWith(live), confirm: vi.fn(), onClose: vi.fn() }))
        }
        await renderWithProviders(createElement(Host), cleanups)
        expect(dialog()!.textContent).toContain('supplementary.consent.zevHeld')

        // The create succeeded and the lists refetched: the one-time token dialog must not turn into the status dialog.
        await click(document.querySelector<HTMLElement>('[data-testid="source-created"]')!)
        expect(dialog()!.textContent).toContain('supplementary.consent.zevHeld')
    })

    it('opens the status dialog for a point that already has a live source', async () => {
        await renderWithProviders(createElement(PointLiveDialog, { point: mp, setup: setupWith('src-live'), confirm: vi.fn(), onClose: vi.fn() }), cleanups)

        expect(dialog()!.textContent).toContain('supplementary.live.dialogTitle')
        expect(dialog()!.textContent).not.toContain('supplementary.consent.zevHeld')
    })
})
