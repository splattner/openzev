import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EnergyDataSection } from '../src/features/account/EnergyDataSection'
import type { EligibleMeteringPoint, SupplementarySource } from '../src/types/api'
import { renderWithProviders, setInputValue } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key}${JSON.stringify(options)}` : key) }),
}))

const pushToast = vi.fn()
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: actual.DEFAULT_APP_SETTINGS, isLoading: false }) }
})
vi.mock('../src/lib/clipboard', () => ({ copyToClipboard: vi.fn().mockResolvedValue(true) }))

const api = vi.hoisted(() => ({
    listSupplementarySources: vi.fn(),
    listEligibleMeteringPoints: vi.fn(),
    fetchEligibleOrNull: vi.fn(),
    createSupplementarySource: vi.fn(),
    updateSupplementarySource: vi.fn(),
    deleteSupplementarySource: vi.fn(),
    disconnectSupplementarySource: vi.fn(),
    purgeSupplementaryReadings: vi.fn(),
    testSupplementarySource: vi.fn(),
    syncSupplementarySource: vi.fn(),
    rotateSupplementaryPushToken: vi.fn(),
    importSupplementaryCsv: vi.fn(),
}))
vi.mock('../src/lib/api/supplementary', () => api)

const point: EligibleMeteringPoint = {
    metering_point: 'mp-1', meter_id: 'CH-100', zev: 'zev-1', zev_name: 'Sonnenhof', participant: 'p-1', source: null,
}

const source = (overrides: Partial<SupplementarySource> = {}): SupplementarySource => ({
    id: 'src-1', metering_point: 'mp-1', metering_point_meter_id: 'CH-100', participant: 'p-1', participant_name: 'Pia Muster',
    provider: 'solar_manager', label: '', external_id: 'ABC123', enabled: true, status: 'ok', consented_at: '2026-07-01T00:00:00Z',
    last_sync_at: '2026-07-03T10:00:00Z', last_success_at: '2026-07-03T10:00:00Z', last_error: '',
    synced_through: '2026-07-03T10:00:00Z', covers_from: '2026-07-01T00:00:00Z',
    reconciliation: { state: 'ok', days_compared: 7, export_deviation_pct: 1.2, import_deviation_pct: 0.4, best_shift_intervals: 0 },
    has_credential: true, push_token_prefix: null, created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-03T10:00:00Z',
    ...overrides,
})

const cleanups: Array<() => void> = []

beforeEach(() => {
    vi.clearAllMocks()
    api.fetchEligibleOrNull.mockResolvedValue([point])
    api.listSupplementarySources.mockResolvedValue([])
})
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function mount(sources: SupplementarySource[] = []) {
    api.listSupplementarySources.mockResolvedValue(sources)
    const view = await renderWithProviders(createElement(EnergyDataSection), cleanups)
    await waitForCondition(() => view.container.querySelector('article') !== null, 'the meter card')
    return view
}

const buttons = (root: ParentNode) => Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
const buttonWith = (root: ParentNode, label: string) => buttons(root).find((b) => b.textContent?.includes(label))!
const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]')

async function click(element: HTMLElement) {
    await act(async () => { element.click() })
}

describe('EnergyDataSection without a source', () => {
    it('offers to connect each flagged meter and explains that the data is never billed', async () => {
        const { container } = await mount()

        expect(container.textContent).toContain('CH-100')
        expect(container.textContent).toContain('Sonnenhof')
        expect(container.textContent).toContain('supplementary.section.notConnected')
        expect(container.textContent).toContain('supplementary.section.description')
        expect(buttonWith(container, 'supplementary.section.connect')).toBeDefined()
    })
})

describe('connect modal', () => {
    async function open() {
        const view = await mount()
        await click(buttonWith(view.container, 'supplementary.section.connect'))
        return view
    }

    const submit = () => buttonWith(dialog()!, 'supplementary.modal.connect')

    it('keeps the key write-only and the submit disabled until consent, id and key are given', async () => {
        await open()
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

    it('shows what is stored, who sees it and that it is never used for billing', async () => {
        await open()

        const text = dialog()!.textContent ?? ''
        for (const key of ['stored', 'visible', 'notBilling', 'revoke']) {
            expect(text).toContain(`supplementary.consent.${key}`)
        }
    })

    it('sends the consent and the key once and closes on success', async () => {
        api.createSupplementarySource.mockResolvedValue(source())
        await open()
        const modal = dialog()!
        const [idInput, keyInput] = Array.from(modal.querySelectorAll<HTMLInputElement>('input[type="text"], input[type="password"]'))
        await act(async () => { setInputValue(idInput, ' ABC123 '); setInputValue(keyInput, ' secret-key ') })
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)

        await act(async () => { submit().click() })
        await waitForCondition(() => api.createSupplementarySource.mock.calls.length === 1, 'the create call')

        expect(api.createSupplementarySource).toHaveBeenCalledWith({
            metering_point: 'mp-1', provider: 'solar_manager', label: undefined, external_id: 'ABC123', api_key: 'secret-key', consent: true,
        })
        await waitForCondition(() => dialog() === null, 'the modal to close')
        expect(pushToast).toHaveBeenCalledWith('supplementary.modal.connected', 'success')
    })

    it('shows the vendor\'s rejection next to the key field and stays open', async () => {
        api.createSupplementarySource.mockRejectedValue({ isAxiosError: true, response: { status: 400, data: { api_key: ['Solar Manager did not accept this API key.'] } } })
        await open()
        const modal = dialog()!
        const [idInput, keyInput] = Array.from(modal.querySelectorAll<HTMLInputElement>('input[type="text"], input[type="password"]'))
        await act(async () => { setInputValue(idInput, 'ABC123'); setInputValue(keyInput, 'wrong') })
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)

        await act(async () => { submit().click() })
        await waitForCondition(() => (dialog()?.textContent ?? '').includes('did not accept this API key'), 'the field error')

        expect(dialog()).not.toBeNull()
    })

    it('needs no credentials for a push source and ends on a one-time token screen', async () => {
        api.createSupplementarySource.mockResolvedValue({ ...source({ provider: 'push', external_id: '', has_credential: false }), push_token: 'ozs_abcd_secret' })
        await open()
        const modal = dialog()!
        await click(Array.from(modal.querySelectorAll<HTMLInputElement>('input[type="radio"]'))[1])
        expect(modal.querySelector('input[type="password"]')).toBeNull()
        await click(modal.querySelector<HTMLInputElement>('input[type="checkbox"]')!)
        expect(submit().disabled).toBe(false)

        await act(async () => { submit().click() })
        await waitForCondition(() => document.querySelector('[data-testid="push-token"]') !== null, 'the token')

        expect(document.querySelector('[data-testid="push-token"]')?.textContent).toBe('ozs_abcd_secret')
        expect(dialog()!.textContent).toContain('supplementary.push.shownOnceTitle')
        expect(dialog()!.textContent).toContain('supplementary.push.endpoint')
        expect(dialog()!.textContent).toContain('timestamp,consumption_kwh,production_kwh,import_kwh,export_kwh')

        await click(buttonWith(dialog()!, 'supplementary.push.dismiss'))
        expect(document.querySelector('[data-testid="push-token"]')).toBeNull()
    })
})

describe('source card', () => {
    it('shows status, last sync, coverage and the meter comparison, and never a credential', async () => {
        const { container } = await mount([source()])

        const text = container.textContent ?? ''
        expect(text).toContain('supplementary.status.ok')
        expect(text).toContain('ABC123')
        expect(text).toContain('supplementary.card.coveredRange')
        expect(text).toContain('supplementary.reconciliation.state.ok')
        expect(container.querySelector('input[type="password"]')).toBeNull()
    })

    it('offers test, sync, replace key, disconnect, delete data and remove for a Solar Manager source', async () => {
        const { container } = await mount([source()])

        for (const action of ['test', 'sync', 'replaceKey', 'disconnect', 'deleteData', 'remove']) {
            expect(buttonWith(container, `supplementary.actions.${action}`), action).toBeDefined()
        }
    })

    it('says the key stopped working and offers to reconnect, without a sync button', async () => {
        const { container } = await mount([source({ status: 'reconnect_required', last_error: 'Solar Manager did not accept this API key.' })])

        expect(container.textContent).toContain('supplementary.reconnect.title')
        expect(container.textContent).toContain('did not accept this API key')
        expect(buttonWith(container, 'supplementary.actions.reconnect')).toBeDefined()
        expect(buttonWith(container, 'supplementary.actions.sync').disabled).toBe(true)
    })

    it('shows a disconnected source as such and only offers to reconnect or clean up', async () => {
        const { container } = await mount([source({ enabled: false, status: 'disabled', has_credential: false })])

        expect(container.textContent).toContain('supplementary.disconnectedNote')
        expect(buttons(container).some((b) => b.textContent?.includes('supplementary.actions.test'))).toBe(false)
        expect(buttons(container).some((b) => b.textContent?.includes('supplementary.actions.sync'))).toBe(false)
        expect(buttonWith(container, 'supplementary.actions.reconnect')).toBeDefined()
        expect(buttonWith(container, 'supplementary.actions.deleteData')).toBeDefined()
    })

    it('offers token rotation and CSV import for a push source, not a key', async () => {
        const { container } = await mount([source({ provider: 'push', external_id: '', has_credential: false, push_token_prefix: 'abcd' })])

        expect(buttonWith(container, 'supplementary.actions.rotate')).toBeDefined()
        expect(buttonWith(container, 'supplementary.actions.importCsv')).toBeDefined()
        expect(buttons(container).some((b) => b.textContent?.includes('supplementary.actions.replaceKey'))).toBe(false)
        expect(container.textContent).toContain('ozs_abcd_')
    })

    it('tests the connection and says so', async () => {
        api.testSupplementarySource.mockResolvedValue({ ok: true })
        const { container } = await mount([source()])

        await click(buttonWith(container, 'supplementary.actions.test'))
        await waitForCondition(() => pushToast.mock.calls.length > 0, 'a toast')

        expect(api.testSupplementarySource).toHaveBeenCalledWith('src-1')
        expect(pushToast).toHaveBeenCalledWith('supplementary.actions.testOk', 'success')
    })

    it('tells the participant politely when a sync was just requested', async () => {
        api.syncSupplementarySource.mockRejectedValue({ isAxiosError: true, response: { status: 429, data: { detail: 'wait' } } })
        const { container } = await mount([source()])

        await click(buttonWith(container, 'supplementary.actions.sync'))
        await waitForCondition(() => pushToast.mock.calls.length > 0, 'a toast')

        expect(pushToast).toHaveBeenCalledWith('supplementary.actions.syncCooldown', 'info')
    })

    it('replaces the key with the new one and the id, then reconnects', async () => {
        api.updateSupplementarySource.mockResolvedValue(source())
        const { container } = await mount([source({ status: 'reconnect_required' })])
        await click(buttonWith(container, 'supplementary.actions.reconnect'))
        const form = container.querySelector('form')!
        const keyInput = form.querySelector<HTMLInputElement>('input[type="password"]')!

        await act(async () => setInputValue(keyInput, 'fresh-key'))
        await act(async () => { buttonWith(form, 'supplementary.actions.saveKey').click() })
        await waitForCondition(() => api.updateSupplementarySource.mock.calls.length === 1, 'the update')

        expect(api.updateSupplementarySource).toHaveBeenCalledWith('src-1', { api_key: 'fresh-key', external_id: 'ABC123', enabled: true })
    })

    it('asks before disconnecting, and keeps the data', async () => {
        api.disconnectSupplementarySource.mockResolvedValue(source({ enabled: false }))
        const { container } = await mount([source()])

        await click(buttonWith(container, 'supplementary.actions.disconnect'))
        expect(dialog()!.textContent).toContain('supplementary.confirm.disconnectMessage')
        expect(api.disconnectSupplementarySource).not.toHaveBeenCalled()

        await click(buttonWith(dialog()!, 'supplementary.actions.disconnect'))
        await waitForCondition(() => api.disconnectSupplementarySource.mock.calls.length === 1, 'the disconnect')
        expect(api.purgeSupplementaryReadings).not.toHaveBeenCalled()
    })

    it('asks before deleting the data and before removing the source', async () => {
        api.purgeSupplementaryReadings.mockResolvedValue({ deleted: 12 })
        api.deleteSupplementarySource.mockResolvedValue(undefined)
        const { container } = await mount([source()])

        await click(buttonWith(container, 'supplementary.actions.deleteData'))
        expect(api.purgeSupplementaryReadings).not.toHaveBeenCalled()
        await click(buttonWith(dialog()!, 'supplementary.actions.deleteData'))
        await waitForCondition(() => api.purgeSupplementaryReadings.mock.calls.length === 1, 'the purge')
        expect(api.purgeSupplementaryReadings).toHaveBeenCalledWith('src-1')

        await click(buttonWith(container, 'supplementary.actions.remove'))
        expect(api.deleteSupplementarySource).not.toHaveBeenCalled()
        await click(buttonWith(dialog()!, 'supplementary.actions.remove'))
        await waitForCondition(() => api.deleteSupplementarySource.mock.calls.length === 1, 'the delete')
    })

    it('shows a rotated push token once', async () => {
        api.rotateSupplementaryPushToken.mockResolvedValue({ push_token: 'ozs_wxyz_fresh', push_token_prefix: 'wxyz' })
        const { container } = await mount([source({ provider: 'push', external_id: '', has_credential: false, push_token_prefix: 'abcd' })])

        await click(buttonWith(container, 'supplementary.actions.rotate'))
        await click(buttonWith(dialog()!, 'supplementary.actions.rotate'))
        await waitForCondition(() => container.querySelector('[data-testid="push-token"]') !== null, 'the token')

        expect(container.querySelector('[data-testid="push-token"]')?.textContent).toBe('ozs_wxyz_fresh')
        await click(buttonWith(container, 'supplementary.push.dismiss'))
        expect(container.querySelector('[data-testid="push-token"]')).toBeNull()
    })
})

describe('CSV import', () => {
    it('checks the file first and imports only on request, listing bad rows', async () => {
        api.importSupplementaryCsv.mockResolvedValueOnce({ accepted: 96, updated: 0, rejected: [], dropped_outside_assignment: 0 })
        api.importSupplementaryCsv.mockRejectedValueOnce({
            isAxiosError: true,
            response: { status: 400, data: { detail: 'The file has invalid rows; nothing was imported.', rejected: [{ index: 3, reason: 'import_kwh is negative' }] } },
        })
        const { container } = await mount([source({ provider: 'push', external_id: '', has_credential: false, push_token_prefix: 'abcd' })])
        await click(buttonWith(container, 'supplementary.actions.importCsv'))
        const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
        const file = new File(['timestamp\n'], 'data.csv', { type: 'text/csv' })
        await act(async () => {
            Object.defineProperty(input, 'files', { value: [file], configurable: true })
            input.dispatchEvent(new Event('change', { bubbles: true }))
        })

        await click(buttonWith(container, 'supplementary.csv.check'))
        await waitForCondition(() => api.importSupplementaryCsv.mock.calls.length === 1, 'the dry run')
        expect(api.importSupplementaryCsv).toHaveBeenLastCalledWith('src-1', file, { dryRun: true })
        await waitForCondition(() => (container.textContent ?? '').includes('supplementary.csv.checked'), 'the result')

        await click(buttonWith(container, 'supplementary.csv.import'))
        await waitForCondition(() => (container.textContent ?? '').includes('invalid rows'), 'the error')
        expect(api.importSupplementaryCsv).toHaveBeenLastCalledWith('src-1', file, { dryRun: false })
        expect(container.textContent).toContain('import_kwh is negative')
        expect(container.textContent).toContain('"row":5')
    })
})
