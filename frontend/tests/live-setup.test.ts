import { AxiosError } from 'axios'
import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PushTokenPanel } from '../src/features/supplementary/PushTokenPanel'
import { SupplementarySourceModal, solarHintKey, type ConnectHolder } from '../src/features/supplementary/SupplementarySourceModal'
import type { SupplementarySource } from '../src/types/api'
import { renderWithProviders, setInputValue } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

// The "more actions" menu opens a popup; here its items are laid out where they can be found. The real menu has its own test.
vi.mock('../src/components/ActionMenu', () => ({
    ActionMenu: ({ items, label }: { items: Array<{ key: string; label: string; disabled?: boolean; danger?: boolean; onClick: () => void }>; label: string }) =>
        createElement('div', { role: 'group', 'aria-label': label },
            ...items.map((entry) => createElement('button', { key: entry.key, type: 'button', disabled: entry.disabled, 'data-danger': entry.danger ? 'true' : undefined, onClick: entry.onClick }, entry.label))),
}))

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

describe('solarHintKey', () => {
    it('says what Solar Manager does for the chosen capabilities', () => {
        expect(solarHintKey(true, false)).toBe('solar_manager')
        expect(solarHintKey(false, true)).toBe('solar_manager_live')
        expect(solarHintKey(true, true)).toBe('solar_manager_both')
    })
})

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

    const radio = (modal: HTMLElement, provider: string) =>
        Array.from(modal.querySelectorAll<HTMLInputElement>('input[type="radio"]')).find((r) => r.closest('label')?.textContent?.includes(provider))!

    it('connects live data for a holder as a push source without history, never forecast', async () => {
        const modal = await open('participant')
        // Live can come from Solar Manager or from a push source; Solar Manager is the first choice.
        expect(modal.querySelectorAll('input[type="radio"]')).toHaveLength(2)
        // Live only: the own system sends the power, and there is no file to upload.
        expect(modal.textContent).toContain('supplementary.modal.providerHint.push_live')
        expect(modal.textContent).not.toMatch(/providerHint\.push(?!_live)/)
        await click(radio(modal, 'supplementary.provider.push'))
        expect(modal.querySelector('input[type="password"]')).toBeNull()
        // The submit waits for the consent, and says so.
        expect(modal.textContent).toContain('supplementary.modal.needsConsent')
        expect(buttonWith(modal, 'supplementary.modal.connect')!.disabled).toBe(true)
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

    it('offers Solar Manager for live data and connects it with its id and key, no token', async () => {
        const modal = await open('participant')
        api.createSupplementarySource.mockResolvedValue(liveOnly({ provider: 'solar_manager', push_token_prefix: null, external_id: 'ABC123', has_credential: true }))
        expect(radio(modal, 'supplementary.provider.solar_manager').checked).toBe(true)
        expect(modal.textContent).toContain('supplementary.modal.providerHint.solar_manager_live')
        const [id, key] = [modal.querySelector<HTMLInputElement>('input[type="text"]')!, modal.querySelector<HTMLInputElement>('input[type="password"]')!]
        expect(buttonWith(modal, 'supplementary.modal.connect')!.disabled).toBe(true)
        await act(async () => { setInputValue(id, ' ABC123 '); setInputValue(key, ' the-key ') })
        await submit(modal)

        expect(api.createSupplementarySource.mock.calls[0][0]).toMatchObject({
            metering_point: 'mp-1', provider: 'solar_manager', target: 'metering_point', held_by: 'participant',
            provides_history: false, provides_live: true, external_id: 'ABC123', api_key: 'the-key', consent: true,
        })
        await waitForCondition(() => pushToast.mock.calls.length > 0, 'the success toast')
        expect(pushToast).toHaveBeenCalledWith('supplementary.modal.liveConnectedPull', 'success')
        expect(document.querySelector('[data-testid="push-token"]')).toBeNull()
    })

    it('hands the new source to the host as the dialog closes, so it can open it', async () => {
        const onConnected = vi.fn()
        const onClose = vi.fn()
        const modal = await open('participant', { point, available: ['live'], onConnected, onClose })
        api.createSupplementarySource.mockResolvedValue(liveOnly({ id: 'src-new', provider: 'solar_manager', push_token_prefix: null, external_id: 'ABC123', has_credential: true }))
        await act(async () => {
            setInputValue(modal.querySelector<HTMLInputElement>('input[type="text"]')!, 'ABC123')
            setInputValue(modal.querySelector<HTMLInputElement>('input[type="password"]')!, 'the-key')
        })
        await submit(modal)

        await waitForCondition(() => onClose.mock.calls.length > 0, 'the dialog to close')
        expect(onConnected).toHaveBeenCalledWith(expect.objectContaining({ id: 'src-new' }))
    })

    it('offers Solar Manager for history and live together, with the matching hint', async () => {
        const modal = await open('participant', { point, available: ['history', 'live'], initial: ['history', 'live'] })
        await click(buttonWith(modal, 'supplementary.modal.next')!)

        expect(radio(modal, 'supplementary.provider.solar_manager').checked).toBe(true)
        expect(modal.textContent).toContain('supplementary.modal.providerHint.solar_manager_both')
    })

    it('shows a refused Solar Manager key at the key field', async () => {
        const modal = await open('participant')
        api.createSupplementarySource.mockRejectedValue(apiError({ api_key: ['Solar Manager did not accept this API key.'] }))
        await act(async () => {
            setInputValue(modal.querySelector<HTMLInputElement>('input[type="text"]')!, 'ABC123')
            setInputValue(modal.querySelector<HTMLInputElement>('input[type="password"]')!, 'wrong')
        })
        await submit(modal)

        await waitForCondition(() => (dialog()?.textContent ?? '').includes('did not accept this API key'), 'the key error')
    })

    it('connects a ZEV-operated meter with the ZEV-held confirmation, push only', async () => {
        const modal = await open('zev', { point })
        expect(modal.textContent).not.toContain('supplementary.provider.solar_manager')
        expect(modal.querySelector('input[type="password"]')).toBeNull()
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
        expect(modal.textContent).not.toContain('supplementary.provider.solar_manager')
        expect(modal.querySelector('input[type="password"]')).toBeNull()
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
        await click(radio(modal, 'supplementary.provider.push'))
        api.createSupplementarySource.mockRejectedValue(apiError({ provides_live: ['Live is not available for this source yet.'], held_by: ['Not allowed.'] }))
        await submit(modal)
        await waitForCondition(() => (dialog()?.textContent ?? '').includes('Live is not available'), 'the field error')

        expect(dialog()!.querySelector('[role="alert"]')!.textContent).toContain('Not allowed.')
    })

    it('shows a consent error next to the checkbox', async () => {
        const modal = await open('participant')
        await click(radio(modal, 'supplementary.provider.push'))
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
