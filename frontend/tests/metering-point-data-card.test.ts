import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useQuery } from '@tanstack/react-query'
import { ConfirmDialog, useConfirmDialog } from '../src/components/ConfirmDialog'
import { MeteringPointDataCard } from '../src/features/supplementary/MeteringPointDataCard'
import { queryKeys } from '../src/lib/api/queryKeys'
import type { EligibleMeteringPoint, SupplementarySource } from '../src/types/api'
import { renderWithProviders, setInputValue } from './helpers/render'
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
    listSupplementarySources: vi.fn(),
    createSupplementarySource: vi.fn(),
    updateSupplementarySource: vi.fn(),
    deleteSupplementarySource: vi.fn(),
    disconnectSupplementarySource: vi.fn(),
    purgeSupplementaryReadings: vi.fn(),
    testSupplementarySource: vi.fn(),
    syncSupplementarySource: vi.fn(),
    rotateSupplementaryPushToken: vi.fn(),
    revokeSupplementaryPushToken: vi.fn(),
    importSupplementaryCsv: vi.fn(),
}))
vi.mock('../src/lib/api/supplementary', () => api)

/** A behind-meter point that can have history and live. */
const point: EligibleMeteringPoint = {
    metering_point: 'mp-1', meter_id: 'CH-100', zev: 'zev-1', zev_name: 'Sonnenhof', participant: 'p-1', source: null,
    eligible_capabilities: ['history', 'live'], sources: { history: null, live: null, forecast: null },
}
const consumptionOnly: EligibleMeteringPoint = { ...point, eligible_capabilities: ['live'] }
const legacy: EligibleMeteringPoint = { metering_point: 'mp-1', meter_id: 'CH-100', zev: 'zev-1', zev_name: 'Sonnenhof', participant: 'p-1', source: null }

const source = (overrides: Partial<SupplementarySource> = {}): SupplementarySource => ({
    id: 'src-1', zev: 'zev-1', target: 'metering_point', held_by: 'participant', metering_point: 'mp-1', metering_point_meter_id: 'CH-100',
    participant: 'p-1', participant_name: 'Pia Muster', provides_history: true, provides_live: false, provides_forecast: false,
    live_last_seen_at: null, live_state: null, provider: 'solar_manager', label: '', external_id: 'ABC123', enabled: true, status: 'ok',
    consented_at: '2026-07-01T00:00:00Z', last_sync_at: '2026-07-03T10:00:00Z', last_success_at: '2026-07-03T10:00:00Z', last_error: '',
    synced_through: '2026-07-03T10:00:00Z', covers_from: '2026-07-01T00:00:00Z',
    reconciliation: { state: 'ok', days_compared: 7, export_deviation_pct: 1.2, import_deviation_pct: 0.4, best_shift_intervals: 0 },
    has_credential: true, push_token_prefix: null, push_token_created_at: null, push_token_last_used_at: null,
    created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-03T10:00:00Z',
    ...overrides,
})
const push = (overrides: Partial<SupplementarySource> = {}) => source({ provider: 'push', external_id: '', has_credential: false, push_token_prefix: 'abcd', ...overrides })
const liveOnly = (overrides: Partial<SupplementarySource> = {}) =>
    push({ id: 'src-live', provides_history: false, provides_live: true, live_state: 'fresh', live_last_seen_at: '2026-07-03T10:00:00Z', ...overrides })
const both = (overrides: Partial<SupplementarySource> = {}) => push({ provides_live: true, live_state: 'stale', ...overrides })

const cleanups: Array<() => void> = []

/** What the page around the card provides: the source list and the confirm dialog. */
function Harness({ eligibility }: { eligibility: EligibleMeteringPoint }) {
    const sources = useQuery({ queryKey: queryKeys.metering.supplementarySources(), queryFn: api.listSupplementarySources })
    const { dialog, confirm, handleConfirm, handleCancel, isLoading } = useConfirmDialog()
    if (!sources.data) return null
    return createElement('div', null,
        createElement(MeteringPointDataCard, { point: eligibility, sources: sources.data, confirm }),
        dialog && createElement(ConfirmDialog, { ...dialog, isLoading, onConfirm: handleConfirm, onCancel: handleCancel }),
    )
}

beforeEach(() => {
    vi.clearAllMocks()
    auth.isImpersonating = false
    api.listSupplementarySources.mockResolvedValue([])
})
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function mount(sources: SupplementarySource[] = [], eligibility: EligibleMeteringPoint = point) {
    api.listSupplementarySources.mockResolvedValue(sources)
    const view = await renderWithProviders(createElement(Harness, { eligibility }), cleanups)
    await waitForCondition(() => view.container.querySelector('article') !== null, 'the meter card')
    return view
}

const buttons = (root: ParentNode) => Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
const buttonWith = (root: ParentNode, label: string) => buttons(root).find((b) => b.textContent?.includes(label))!
const primaryConnect = (root: ParentNode) => buttons(root).find((b) => b.textContent === 'supplementary.card.connect')!
const dialogs = () => Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]'))
/** The topmost dialog: a confirmation when one is open over the source dialog. */
const dialog = () => dialogs().at(-1) ?? null
const row = (root: ParentNode, capability: string) => root.querySelector<HTMLElement>(`li[data-capability="${capability}"]`)!

async function click(element: HTMLElement) {
    await act(async () => { element.click() })
}

/** Open the dialog of the source in a capability row. */
async function openSource(container: HTMLElement, capability: 'history' | 'live' = 'history') {
    await click(row(container, capability).querySelector('button')!)
    return dialog()!
}

describe('one card per metering point', () => {
    it('shows a meter with a history source and a separate live source as one card with two rows', async () => {
        const { container } = await mount([source(), liveOnly()])

        expect(container.querySelectorAll('article')).toHaveLength(1)
        expect(container.querySelectorAll('h3')).toHaveLength(1)
        expect(container.textContent).toContain('CH-100')
        expect(container.textContent).toContain('Sonnenhof')
        expect(row(container, 'history').textContent).toContain('supplementary.provider.solar_manager')
        expect(row(container, 'history').textContent).toContain('supplementary.status.ok')
        expect(row(container, 'live').textContent).toContain('supplementary.provider.push')
        expect(row(container, 'live').textContent).toContain('live.state.fresh')
        // Everything is connected: nothing left to connect.
        expect(buttons(container).some((b) => b.textContent === 'supplementary.card.connect')).toBe(false)
    })

    it('shows the behind-meter badge and the metering data link in the header', async () => {
        const { container } = await mount()

        expect(container.querySelector('header')!.textContent).toContain('behindMeter.badge')
        expect(container.querySelector('a')?.getAttribute('href')).toBe('/metering/chart?metering_point=mp-1')
    })

    it('has a row for each capability the point is eligible for, and none for forecast', async () => {
        const full = await mount()
        expect(Array.from(full.container.querySelectorAll('li')).map((li) => li.dataset.capability)).toEqual(['history', 'live'])

        const live = await mount([], consumptionOnly)
        expect(live.container.querySelector('li[data-capability="history"]')).toBeNull()
        expect(live.container.querySelector('li[data-capability="live"]')).not.toBeNull()
        expect(live.container.querySelector('header')!.textContent).not.toContain('behindMeter.badge')

        const old = await mount([], legacy)
        expect(Array.from(old.container.querySelectorAll('li')).map((li) => li.dataset.capability)).toEqual(['history'])
    })

    it('shows "not connected" with a Connect on every unconnected row and one primary Connect', async () => {
        const { container } = await mount([source()])

        expect(row(container, 'history').textContent).not.toContain('supplementary.card.notConnected')
        expect(row(container, 'live').textContent).toContain('supplementary.card.notConnected')
        expect(buttons(row(container, 'live')).some((b) => b.textContent === 'supplementary.card.connectRow')).toBe(true)
        expect(buttons(container).filter((b) => b.textContent === 'supplementary.card.connect')).toHaveLength(1)
    })

    it('keeps a shared push source in both rows and opens one dialog for it', async () => {
        const { container } = await mount([both()])

        const historyButton = row(container, 'history').querySelector('button')!
        const liveButton = row(container, 'live').querySelector('button')!
        expect(historyButton.textContent).toBe(liveButton.textContent)
        expect(row(container, 'history').textContent).toContain('supplementary.status.ok')
        expect(row(container, 'live').textContent).toContain('live.state.stale')

        await click(historyButton)
        expect(dialogs()).toHaveLength(1)
        expect(dialog()!.textContent).toContain('supplementary.source.title{"subject":"CH-100"}')
        expect(dialog()!.textContent).toContain('ozs_abcd_')
        expect(dialog()!.textContent).toContain('supplementary.capability.history')
        expect(dialog()!.textContent).toContain('supplementary.capability.live')
    })

    it('shows the reconnect banner of a history source on the card', async () => {
        const { container } = await mount([source({ status: 'reconnect_required', last_error: 'Solar Manager did not accept this API key.' })])

        expect(container.querySelector('article > [role="alert"]')!.textContent).toContain('did not accept this API key')
    })
})

describe('impersonation', () => {
    it('disables every way to connect, and rotating a token, but not reading', async () => {
        auth.isImpersonating = true
        const unconnected = await mount()
        expect(buttons(unconnected.container).filter((b) => b.textContent?.includes('supplementary.card.connect')).every((b) => b.disabled)).toBe(true)
        await click(primaryConnect(unconnected.container))
        expect(dialog()).toBeNull()

        const connected = await mount([push()])
        const modal = await openSource(connected.container)
        const rotate = buttonWith(modal, 'supplementary.actions.rotate')
        expect(rotate.disabled).toBe(true)
        expect(buttonWith(modal, 'supplementary.actions.importCsv').disabled).toBe(false)
        await click(rotate)
        expect(dialogs()).toHaveLength(1)
        expect(api.rotateSupplementaryPushToken).not.toHaveBeenCalled()
    })
})

describe('a source that eligibility knows about but whose details are missing', () => {
    const known = { ...point, source: 'src-1' }
    const render = (props: { sourcesUnavailable?: 'loading' | 'error'; onRetrySources?: () => void }) =>
        renderWithProviders(createElement(MeteringPointDataCard, { point: known, sources: undefined, confirm: vi.fn(), ...props }), cleanups)

    it.each(['loading', 'error'] as const)('does not offer Connect while the details are %s', async (state) => {
        const { container } = await render({ sourcesUnavailable: state })

        expect(container.querySelector('li')).toBeNull()
        expect(buttons(container).some((b) => b.textContent?.includes('supplementary.card.connect'))).toBe(false)
        expect(container.querySelector('a')?.getAttribute('href')).toBe('/metering/chart?metering_point=mp-1')
    })

    it('offers a retry when they failed to load', async () => {
        const retry = vi.fn()
        const { container } = await render({ sourcesUnavailable: 'error', onRetrySources: retry })

        await click(buttonWith(container, 'common.retry'))
        expect(retry).toHaveBeenCalledOnce()
    })

    it('offers Connect again once the list is known not to contain the source', async () => {
        const { container } = await renderWithProviders(createElement(MeteringPointDataCard, { point: known, sources: [], confirm: vi.fn() }), cleanups)

        expect(primaryConnect(container)).toBeDefined()
    })

    it('does not wait for the list for a point that has no source', async () => {
        const { container } = await renderWithProviders(createElement(MeteringPointDataCard, { point, sources: undefined, sourcesUnavailable: 'loading', confirm: vi.fn() }), cleanups)

        expect(primaryConnect(container)).toBeDefined()
    })
})

describe('connect flow', () => {
    const checkboxes = (modal: HTMLElement) => Array.from(modal.querySelectorAll<HTMLInputElement>('input[name="supplementary-capability"]'))
    const radios = (modal: HTMLElement) => Array.from(modal.querySelectorAll<HTMLInputElement>('input[type="radio"]'))
    const submit = () => buttonWith(dialog()!, 'supplementary.modal.connect')

    it('preselects what a row\'s Connect is for, and everything left for the primary Connect', async () => {
        const { container } = await mount()
        await click(buttons(row(container, 'live')).find((b) => b.textContent === 'supplementary.card.connectRow')!)
        expect(checkboxes(dialog()!).map((c) => c.checked)).toEqual([false, true])
        expect(dialog()!.textContent).toContain('supplementary.modal.what')
        await click(buttonWith(dialog()!, 'common.cancel'))
        expect(dialog()).toBeNull()

        await click(primaryConnect(container))
        expect(checkboxes(dialog()!).map((c) => c.checked)).toEqual([true, true])
    })

    it('only offers the capabilities that are not connected yet', async () => {
        const { container } = await mount([source()])
        await click(primaryConnect(container))

        // One left, so there is nothing to choose: the flow starts at "how".
        expect(checkboxes(dialog()!)).toHaveLength(0)
        expect(dialog()!.textContent).toContain('supplementary.modal.provider')
        expect(dialog()!.textContent).toContain('supplementary.consent.liveVisible')
        expect(dialog()!.textContent).not.toContain('supplementary.consent.stored')
    })

    it('filters the providers by what is chosen: Solar Manager only for history', async () => {
        const { container } = await mount()
        await click(primaryConnect(container))
        const modal = dialog()!

        // history + live: push only
        await click(buttonWith(modal, 'supplementary.modal.next'))
        expect(radios(dialog()!)).toHaveLength(1)
        expect(dialog()!.textContent).not.toContain('supplementary.provider.solar_manager')
        // history only: Solar Manager and push
        await click(buttonWith(dialog()!, 'supplementary.modal.back'))
        await click(checkboxes(dialog()!)[1])
        await click(buttonWith(dialog()!, 'supplementary.modal.next'))
        expect(radios(dialog()!)).toHaveLength(2)
        expect(dialog()!.textContent).toContain('supplementary.provider.solar_manager')
        // live only: push only
        await click(buttonWith(dialog()!, 'supplementary.modal.back'))
        await click(checkboxes(dialog()!)[1])
        await click(checkboxes(dialog()!)[0])
        await click(buttonWith(dialog()!, 'supplementary.modal.next'))
        expect(radios(dialog()!)).toHaveLength(1)
    })

    it('cannot go on without choosing something', async () => {
        const { container } = await mount()
        await click(primaryConnect(container))
        await click(checkboxes(dialog()!)[0])
        await click(checkboxes(dialog()!)[1])

        expect(buttonWith(dialog()!, 'supplementary.modal.next').disabled).toBe(true)
    })

    it('creates one push source with history and live in one request, and shows both endpoints once', async () => {
        const created = both()
        api.createSupplementarySource.mockResolvedValue({ ...created, push_token: 'ozs_abcd_secret' })
        const { container } = await mount()
        await click(primaryConnect(container))
        await click(buttonWith(dialog()!, 'supplementary.modal.next'))
        const modal = dialog()!
        for (const key of ['stored', 'visible', 'notBilling', 'revoke', 'liveVisible', 'liveNotBilling', 'liveRevoke']) {
            expect(modal.textContent).toContain(`supplementary.consent.${key}`)
        }
        expect(modal.textContent).toContain('supplementary.consent.bothAgree')
        expect(submit().disabled).toBe(true)
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
        // The list now has the source, as it does once the invalidation has refetched it.
        api.listSupplementarySources.mockResolvedValue([created])
        await act(async () => { submit().click() })
        await waitForCondition(() => document.querySelector('[data-testid="push-token"]') !== null, 'the token')

        expect(api.createSupplementarySource).toHaveBeenCalledTimes(1)
        expect(api.createSupplementarySource).toHaveBeenCalledWith({
            metering_point: 'mp-1', target: 'metering_point', held_by: 'participant', provider: 'push', label: undefined,
            provides_history: true, provides_live: true, external_id: undefined, api_key: undefined, consent: true,
        })
        expect(document.querySelector('[data-testid="push-token"]')!.textContent).toBe('ozs_abcd_secret')
        expect(document.querySelector('[data-testid="live-endpoint"]')).not.toBeNull()
        expect(dialog()!.textContent).toContain('supplementary.push.columns')
    })

    it('keeps the one-time token on screen when the refreshed source list changes the card behind it', async () => {
        const created = push()
        api.createSupplementarySource.mockResolvedValue({ ...created, push_token: 'ozs_abcd_secret' })
        const { container } = await mount([], legacy)
        await click(primaryConnect(container))
        const modal = dialog()!
        await click(radios(modal)[1])
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
        api.listSupplementarySources.mockResolvedValue([created])

        await act(async () => { submit().click() })
        await waitForCondition(() => document.querySelector('[data-testid="push-token"]') !== null, 'the token')
        await waitForCondition(() => container.textContent?.includes('supplementary.status.ok') ?? false, 'the connected card')

        expect(document.querySelector('[data-testid="push-token"]')?.textContent).toBe('ozs_abcd_secret')
        await click(buttonWith(dialog()!, 'supplementary.push.dismiss'))
        expect(document.querySelector('[data-testid="push-token"]')).toBeNull()
        expect(dialog()).toBeNull()
    })

    it('offers the point\'s own push source first and adds the capability to it with the consent, without a new token', async () => {
        api.updateSupplementarySource.mockResolvedValue(both())
        const { container } = await mount([push()])
        await click(primaryConnect(container))
        const modal = dialog()!

        expect(radios(modal).map((r) => r.checked)).toEqual([true, false])
        expect(modal.textContent).toContain('supplementary.modal.existingPush')
        expect(modal.textContent).not.toContain('supplementary.provider.solar_manager')
        expect(modal.querySelector('input[type="text"]')).toBeNull()
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
        await act(async () => { submit().click() })
        await waitForCondition(() => api.updateSupplementarySource.mock.calls.length === 1, 'the update')

        expect(api.updateSupplementarySource).toHaveBeenCalledWith('src-1', { consent: true, provides_live: true })
        expect(api.createSupplementarySource).not.toHaveBeenCalled()
        await waitForCondition(() => dialog()!.textContent?.includes('supplementary.modal.existingReadyTitle') ?? false, 'the endpoints')
        expect(dialog()!.textContent).toContain('ozs_abcd_')
        expect(document.querySelector('[data-testid="live-endpoint"]')).not.toBeNull()
        expect(document.querySelector('[data-testid="push-token"]')).toBeNull()
    })

    it('does not offer a Solar Manager history source to carry live data', async () => {
        const { container } = await mount([source()])
        await click(primaryConnect(container))

        expect(dialog()!.textContent).not.toContain('supplementary.modal.existingPush')
        expect(radios(dialog()!)).toHaveLength(1)
    })

    it('keeps the key write-only and the submit disabled until consent, id and key are given', async () => {
        const { container } = await mount([], legacy)
        await click(primaryConnect(container))
        const modal = dialog()!
        const [idInput, keyInput] = Array.from(modal.querySelectorAll<HTMLInputElement>('input[type="text"], input[type="password"]'))

        expect(keyInput.type).toBe('password')
        expect(keyInput.autocomplete).toBe('new-password')
        expect(submit().disabled).toBe(true)
        await act(async () => { setInputValue(idInput, 'ABC123'); setInputValue(keyInput, 'secret-key') })
        expect(submit().disabled).toBe(true) // still no consent
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
        expect(submit().disabled).toBe(false)
    })

    it('sends the consent and the key once and closes on success', async () => {
        api.createSupplementarySource.mockResolvedValue(source())
        const { container } = await mount([], legacy)
        await click(primaryConnect(container))
        const modal = dialog()!
        const [idInput, keyInput] = Array.from(modal.querySelectorAll<HTMLInputElement>('input[type="text"], input[type="password"]'))
        await act(async () => { setInputValue(idInput, ' ABC123 '); setInputValue(keyInput, ' secret-key ') })
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)

        await act(async () => { submit().click() })
        await waitForCondition(() => api.createSupplementarySource.mock.calls.length === 1, 'the create call')

        expect(api.createSupplementarySource).toHaveBeenCalledWith({
            metering_point: 'mp-1', target: 'metering_point', held_by: 'participant', provider: 'solar_manager', label: undefined,
            provides_history: true, provides_live: false, external_id: 'ABC123', api_key: 'secret-key', consent: true,
        })
        await waitForCondition(() => dialog() === null, 'the modal to close')
        expect(pushToast).toHaveBeenCalledWith('supplementary.modal.connected', 'success')
    })

    it('shows the vendor\'s rejection next to the key field and stays open', async () => {
        api.createSupplementarySource.mockRejectedValue({ isAxiosError: true, response: { status: 400, data: { api_key: ['Solar Manager did not accept this API key.'] } } })
        const { container } = await mount([], legacy)
        await click(primaryConnect(container))
        const modal = dialog()!
        const [idInput, keyInput] = Array.from(modal.querySelectorAll<HTMLInputElement>('input[type="text"], input[type="password"]'))
        await act(async () => { setInputValue(idInput, 'ABC123'); setInputValue(keyInput, 'wrong') })
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)

        await act(async () => { submit().click() })
        await waitForCondition(() => (dialog()?.textContent ?? '').includes('did not accept this API key'), 'the field error')

        expect(dialog()).not.toBeNull()
    })

    it('shows a refused capability as a banner and a consent error next to the checkbox', async () => {
        api.createSupplementarySource.mockRejectedValue({
            isAxiosError: true,
            response: { status: 400, data: { provides_live: ['Live data is only available for push sources.'], consent: ['Consent is required.'] } },
        })
        const { container } = await mount([], consumptionOnly)
        await click(primaryConnect(container))
        await click(dialog()!.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
        await act(async () => { submit().click() })
        await waitForCondition(() => (dialog()?.textContent ?? '').includes('Consent is required.'), 'the errors')

        expect(dialog()!.querySelector('[role="alert"]')!.textContent).toContain('only available for push sources')
        expect(dialog()!.querySelector('.field-error')!.textContent).toBe('Consent is required.')
    })
})

describe('source dialog', () => {
    it('shows provider, capabilities, status, coverage and the meter comparison, and never a credential', async () => {
        const { container } = await mount([source()])
        const modal = await openSource(container)

        const text = modal.textContent ?? ''
        expect(text).toContain('supplementary.provider.solar_manager')
        expect(text).toContain('supplementary.status.ok')
        expect(text).toContain('ABC123')
        expect(text).toContain('supplementary.card.coveredRange')
        expect(text).toContain('supplementary.reconciliation.state.ok')
        expect(modal.querySelector('input[type="password"]')).toBeNull()
    })

    it('offers test, sync, replace key, disconnect, delete data and remove for a Solar Manager source', async () => {
        const { container } = await mount([source()])
        const modal = await openSource(container)

        for (const action of ['test', 'sync', 'replaceKey', 'disconnect', 'deleteData', 'remove']) {
            expect(buttonWith(modal, `supplementary.actions.${action}`), action).toBeDefined()
        }
        expect(buttons(modal).some((b) => b.textContent?.includes('supplementary.actions.rotate'))).toBe(false)
    })

    it('says the key stopped working and offers to reconnect, without a usable sync button', async () => {
        const { container } = await mount([source({ status: 'reconnect_required', last_error: 'Solar Manager did not accept this API key.' })])
        const modal = await openSource(container)

        expect(modal.textContent).toContain('supplementary.reconnect.title')
        expect(buttonWith(modal, 'supplementary.actions.reconnect')).toBeDefined()
        expect(buttonWith(modal, 'supplementary.actions.sync').disabled).toBe(true)
    })

    it('shows a disconnected source as such and only offers to reconnect or clean up', async () => {
        const { container } = await mount([source({ enabled: false, status: 'disabled', has_credential: false })])
        expect(row(container, 'history').textContent).toContain('supplementary.status.disabled')
        const modal = await openSource(container)

        expect(modal.textContent).toContain('supplementary.disconnectedNote')
        expect(buttons(modal).some((b) => b.textContent?.includes('supplementary.actions.test'))).toBe(false)
        expect(buttons(modal).some((b) => b.textContent?.includes('supplementary.actions.sync'))).toBe(false)
        expect(buttonWith(modal, 'supplementary.actions.reconnect')).toBeDefined()
        expect(buttonWith(modal, 'supplementary.actions.deleteData')).toBeDefined()
    })

    it('shows a push source\'s token prefix, endpoints, rotation, revocation and CSV import, not a key', async () => {
        const { container } = await mount([push()])
        const modal = await openSource(container)

        for (const action of ['supplementary.actions.rotate', 'supplementary.live.revoke', 'supplementary.actions.importCsv']) {
            expect(buttonWith(modal, action), action).toBeDefined()
        }
        expect(buttons(modal).some((b) => b.textContent?.includes('supplementary.actions.replaceKey'))).toBe(false)
        expect(modal.textContent).toContain('ozs_abcd_')
        expect(modal.querySelector('details')).not.toBeNull()
        expect(modal.querySelector('[data-testid="live-endpoint"]')).toBeNull()
    })

    it('shows the live endpoint of a live source, with live actions and no history actions', async () => {
        const { container } = await mount([liveOnly()])
        const modal = await openSource(container, 'live')

        expect(modal.textContent).toContain('live.state.fresh')
        expect(modal.querySelector('[data-testid="live-endpoint"]')).not.toBeNull()
        expect(modal.textContent).not.toContain('supplementary.push.columns')
        for (const action of ['supplementary.actions.rotate', 'supplementary.live.revoke', 'supplementary.actions.disconnect', 'supplementary.actions.remove']) {
            expect(buttonWith(modal, action), action).toBeDefined()
        }
        for (const action of ['supplementary.live.stop', 'supplementary.actions.deleteData', 'supplementary.actions.importCsv']) {
            expect(buttons(modal).some((b) => b.textContent?.includes(action)), action).toBe(false)
        }
    })

    it('tests the connection and says so', async () => {
        api.testSupplementarySource.mockResolvedValue({ ok: true })
        const { container } = await mount([source()])
        const modal = await openSource(container)

        await click(buttonWith(modal, 'supplementary.actions.test'))
        await waitForCondition(() => pushToast.mock.calls.length > 0, 'a toast')

        expect(api.testSupplementarySource).toHaveBeenCalledWith('src-1')
        expect(pushToast).toHaveBeenCalledWith('supplementary.actions.testOk', 'success')
    })

    it('tells the participant politely when a sync was just requested', async () => {
        api.syncSupplementarySource.mockRejectedValue({ isAxiosError: true, response: { status: 429, data: { detail: 'wait' } } })
        const { container } = await mount([source()])
        const modal = await openSource(container)

        await click(buttonWith(modal, 'supplementary.actions.sync'))
        await waitForCondition(() => pushToast.mock.calls.length > 0, 'a toast')

        expect(pushToast).toHaveBeenCalledWith('supplementary.actions.syncCooldown', 'info')
    })

    it('replaces the key with the new one and the id, then reconnects', async () => {
        api.updateSupplementarySource.mockResolvedValue(source())
        const { container } = await mount([source({ status: 'reconnect_required' })])
        const modal = await openSource(container)
        await click(buttonWith(modal, 'supplementary.actions.reconnect'))
        const form = modal.querySelector('form')!
        const keyInput = form.querySelector<HTMLInputElement>('input[type="password"]')!

        await act(async () => setInputValue(keyInput, 'fresh-key'))
        await act(async () => { buttonWith(form, 'supplementary.actions.saveKey').click() })
        await waitForCondition(() => api.updateSupplementarySource.mock.calls.length === 1, 'the update')

        expect(api.updateSupplementarySource).toHaveBeenCalledWith('src-1', { api_key: 'fresh-key', external_id: 'ABC123', enabled: true })
    })

    it('asks before disconnecting, and keeps the data', async () => {
        api.disconnectSupplementarySource.mockResolvedValue(source({ enabled: false }))
        const { container } = await mount([source()])
        const modal = await openSource(container)

        await click(buttonWith(modal, 'supplementary.actions.disconnect'))
        expect(dialog()!.textContent).toContain('supplementary.confirm.disconnectMessage')
        expect(api.disconnectSupplementarySource).not.toHaveBeenCalled()

        await click(buttonWith(dialog()!, 'supplementary.actions.disconnect'))
        await waitForCondition(() => api.disconnectSupplementarySource.mock.calls.length === 1, 'the disconnect')
        expect(api.purgeSupplementaryReadings).not.toHaveBeenCalled()
    })

    it('asks before deleting the data and before removing the source, and closes once it is gone', async () => {
        api.purgeSupplementaryReadings.mockResolvedValue({ deleted: 12 })
        api.deleteSupplementarySource.mockResolvedValue(undefined)
        const { container } = await mount([source()])
        const modal = await openSource(container)

        await click(buttonWith(modal, 'supplementary.actions.deleteData'))
        expect(api.purgeSupplementaryReadings).not.toHaveBeenCalled()
        await click(buttonWith(dialog()!, 'supplementary.actions.deleteData'))
        await waitForCondition(() => api.purgeSupplementaryReadings.mock.calls.length === 1, 'the purge')
        expect(api.purgeSupplementaryReadings).toHaveBeenCalledWith('src-1')

        await click(buttonWith(modal, 'supplementary.actions.remove'))
        expect(api.deleteSupplementarySource).not.toHaveBeenCalled()
        await click(buttonWith(dialog()!, 'supplementary.actions.remove'))
        await waitForCondition(() => api.deleteSupplementarySource.mock.calls.length === 1, 'the delete')
        await waitForCondition(() => dialogs().length === 0, 'the dialogs to close')
    })

    it('shows a rotated push token once, with the endpoints of everything the source provides', async () => {
        api.rotateSupplementaryPushToken.mockResolvedValue({ push_token: 'ozs_wxyz_fresh', push_token_prefix: 'wxyz' })
        const { container } = await mount([both()])
        const modal = await openSource(container)

        await click(buttonWith(modal, 'supplementary.actions.rotate'))
        await click(buttonWith(dialog()!, 'supplementary.actions.rotate'))
        await waitForCondition(() => document.querySelector('[data-testid="push-token"]') !== null, 'the token')

        expect(document.querySelector('[data-testid="push-token"]')?.textContent).toBe('ozs_wxyz_fresh')
        expect(document.querySelector('[data-testid="live-endpoint"]')).not.toBeNull()
        expect(modal.textContent).toContain('supplementary.push.columns')
        await click(buttonWith(modal, 'supplementary.push.dismiss'))
        expect(document.querySelector('[data-testid="push-token"]')).toBeNull()
    })

    it('keeps a rotated token on screen when the refreshed list changes the source', async () => {
        api.rotateSupplementaryPushToken.mockResolvedValue({ push_token: 'ozs_wxyz_fresh', push_token_prefix: 'wxyz' })
        const { container } = await mount([push()])
        const modal = await openSource(container)
        api.listSupplementarySources.mockResolvedValue([push({ push_token_prefix: 'wxyz' })])

        await click(buttonWith(modal, 'supplementary.actions.rotate'))
        await click(buttonWith(dialog()!, 'supplementary.actions.rotate'))
        await waitForCondition(() => modal.textContent?.includes('ozs_wxyz_') ?? false, 'the refetched prefix')

        expect(document.querySelector('[data-testid="push-token"]')?.textContent).toBe('ozs_wxyz_fresh')
    })

    it('revokes the token after asking', async () => {
        api.revokeSupplementaryPushToken.mockResolvedValue(push())
        const { container } = await mount([push()])
        const modal = await openSource(container)

        await click(buttonWith(modal, 'supplementary.live.revoke'))
        expect(api.revokeSupplementaryPushToken).not.toHaveBeenCalled()
        await click(buttonWith(dialog()!, 'supplementary.live.revoke'))
        await waitForCondition(() => api.revokeSupplementaryPushToken.mock.calls.length === 1, 'the revoke')
    })

    it('adds live data to a push history source after the live consent', async () => {
        api.updateSupplementarySource.mockResolvedValue(both())
        const { container } = await mount([push()])
        const modal = await openSource(container)

        await click(buttonWith(modal, 'supplementary.live.alsoSend'))
        expect(dialog()!.textContent).toContain('supplementary.consent.liveVisible')
        await click(buttonWith(dialog()!, 'supplementary.live.alsoSend'))
        await waitForCondition(() => api.updateSupplementarySource.mock.calls.length === 1, 'the update')

        expect(api.updateSupplementarySource).toHaveBeenCalledWith('src-1', { provides_live: true, consent: true })
    })

    it('does not offer live data on a Solar Manager source', async () => {
        const { container } = await mount([source()])
        const modal = await openSource(container)

        expect(buttons(modal).some((b) => b.textContent?.includes('supplementary.live.alsoSend'))).toBe(false)
    })

    it('does not offer live data on a point that is not live-eligible', async () => {
        const { container } = await mount([push()], legacy)
        const modal = await openSource(container)

        expect(buttons(modal).some((b) => b.textContent?.includes('supplementary.live.alsoSend'))).toBe(false)
    })

    it('stops live data on a source shared with history instead of disconnecting it', async () => {
        api.updateSupplementarySource.mockResolvedValue(push())
        const { container } = await mount([both()])
        const modal = await openSource(container, 'live')

        await click(buttonWith(modal, 'supplementary.live.stop'))
        await click(buttonWith(dialog()!, 'supplementary.live.stop'))
        await waitForCondition(() => api.updateSupplementarySource.mock.calls.length === 1, 'the update')

        expect(api.updateSupplementarySource).toHaveBeenCalledWith('src-1', { provides_live: false })
    })

    it('adds history to a live push source and stops it again while live remains', async () => {
        api.updateSupplementarySource.mockResolvedValue(both())
        const live = await mount([liveOnly()])
        const modal = await openSource(live.container, 'live')
        expect(buttons(modal).some((b) => b.textContent?.includes('supplementary.source.stopHistory'))).toBe(false)

        await click(buttonWith(modal, 'supplementary.source.alsoHistory'))
        expect(dialog()!.textContent).toContain('supplementary.consent.stored')
        await click(buttonWith(dialog()!, 'supplementary.source.alsoHistory'))
        await waitForCondition(() => api.updateSupplementarySource.mock.calls.length === 1, 'the update')
        expect(api.updateSupplementarySource).toHaveBeenLastCalledWith('src-live', { provides_history: true, consent: true })
    })

    it('stops history on a source shared with live', async () => {
        api.updateSupplementarySource.mockResolvedValue(liveOnly())
        const { container } = await mount([both()])
        const modal = await openSource(container)

        await click(buttonWith(modal, 'supplementary.source.stopHistory'))
        await click(buttonWith(dialog()!, 'supplementary.source.stopHistory'))
        await waitForCondition(() => api.updateSupplementarySource.mock.calls.length === 1, 'the update')

        expect(api.updateSupplementarySource).toHaveBeenCalledWith('src-1', { provides_history: false })
    })

    it('does not offer history on a consumption-only meter', async () => {
        const { container } = await mount([liveOnly()], consumptionOnly)
        const modal = await openSource(container, 'live')

        expect(buttons(modal).some((b) => b.textContent?.includes('supplementary.source.alsoHistory'))).toBe(false)
    })
})

describe('CSV import', () => {
    it('checks the file first and imports only on request, listing bad rows', async () => {
        api.importSupplementaryCsv.mockResolvedValueOnce({ accepted: 96, updated: 0, rejected: [], dropped_outside_assignment: 0 })
        api.importSupplementaryCsv.mockRejectedValueOnce({
            isAxiosError: true,
            response: { status: 400, data: { detail: 'The file has invalid rows; nothing was imported.', rejected: [{ index: 3, reason: 'import_kwh is negative' }] } },
        })
        const { container } = await mount([push()])
        const modal = await openSource(container)
        await click(buttonWith(modal, 'supplementary.actions.importCsv'))
        const input = modal.querySelector<HTMLInputElement>('input[type="file"]')!
        const file = new File(['timestamp\n'], 'data.csv', { type: 'text/csv' })
        await act(async () => {
            Object.defineProperty(input, 'files', { value: [file], configurable: true })
            input.dispatchEvent(new Event('change', { bubbles: true }))
        })

        await click(buttonWith(modal, 'supplementary.csv.check'))
        await waitForCondition(() => api.importSupplementaryCsv.mock.calls.length === 1, 'the dry run')
        expect(api.importSupplementaryCsv).toHaveBeenLastCalledWith('src-1', file, { dryRun: true })
        await waitForCondition(() => (modal.textContent ?? '').includes('supplementary.csv.checked'), 'the result')

        await click(buttonWith(modal, 'supplementary.csv.import'))
        await waitForCondition(() => (modal.textContent ?? '').includes('invalid rows'), 'the error')
        expect(api.importSupplementaryCsv).toHaveBeenLastCalledWith('src-1', file, { dryRun: false })
        expect(modal.textContent).toContain('import_kwh is negative')
        expect(modal.textContent).toContain('"row":5')
    })
})
