import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ZevEnergySources } from '../src/features/supplementary/ZevEnergySources'
import type { SupplementarySource, ZevEligibleSources } from '../src/types/api'
import { renderWithDataRouter } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

// The "more actions" menu opens a popup; here its items are laid out where they can be found (it has its own test).
vi.mock('../src/components/ActionMenu', () => ({
    ActionMenu: ({ items, label }: { items: Array<{ key: string; label: string; disabled?: boolean; danger?: boolean; onClick: () => void }>; label: string }) =>
        createElement('div', { role: 'group', 'aria-label': label },
            ...items.map((entry) => createElement('button', { key: entry.key, type: 'button', disabled: entry.disabled, 'data-danger': entry.danger ? 'true' : undefined, onClick: entry.onClick }, entry.label))),
}))
vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key}${JSON.stringify(options)}` : key) }),
}))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ isImpersonating: false }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: actual.DEFAULT_APP_SETTINGS, isLoading: false }) }
})

const api = vi.hoisted(() => ({
    listSupplementarySources: vi.fn(),
    fetchZevEligibleSources: vi.fn(),
    fetchEligibleOrNull: vi.fn(),
    createSupplementarySource: vi.fn(),
    updateSupplementarySource: vi.fn(),
    deleteSupplementarySource: vi.fn(),
    disconnectSupplementarySource: vi.fn(),
    purgeSupplementaryReadings: vi.fn(),
    testSupplementarySource: vi.fn(),
    syncSupplementarySource: vi.fn(),
    rotateSupplementaryPushToken: vi.fn(),
    revokeSupplementaryPushToken: vi.fn(),
}))
vi.mock('../src/lib/api/supplementary', () => api)
const live = vi.hoisted(() => ({ fetchLiveEnabled: vi.fn() }))
vi.mock('../src/lib/api/live', async (importOriginal) => ({ ...(await importOriginal<typeof import('../src/lib/api/live')>()), ...live }))

const base: SupplementarySource = {
    id: 'src', zev: 'zev-1', target: 'metering_point', held_by: 'zev', metering_point: 'mp-2', metering_point_meter_id: 'CH-200',
    participant: null, participant_name: null, provides_history: false, provides_live: true, provides_forecast: false,
    live_last_seen_at: '2026-07-03T10:00:00Z', live_state: 'fresh', provider: 'push', label: '', external_id: '', enabled: true, status: 'ok',
    consented_at: '2026-07-01T00:00:00Z', last_sync_at: null, last_success_at: null, last_error: '', synced_through: null, covers_from: null,
    reconciliation: {}, has_credential: false, push_token_prefix: 'abcd', push_token_created_at: '2026-07-01T00:00:00Z', push_token_last_used_at: null,
    created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-03T10:00:00Z',
} as SupplementarySource
const zevSource = (overrides: Partial<SupplementarySource> = {}): SupplementarySource => ({ ...base, id: 'src-zev', ...overrides })
const participantSource = (overrides: Partial<SupplementarySource> = {}): SupplementarySource => ({
    ...base, id: 'src-part', held_by: 'participant', metering_point: 'mp-1', metering_point_meter_id: 'CH-100', participant: 'p-1', participant_name: 'Pia Muster',
    provides_history: true, provider: 'solar_manager', external_id: 'ABC123', has_credential: true, push_token_prefix: null, ...overrides,
})
const connectionSource = (overrides: Partial<SupplementarySource> = {}): SupplementarySource =>
    ({ ...base, id: 'src-cp', target: 'connection_point', metering_point: null, metering_point_meter_id: null, ...overrides })

const eligibility = (overrides: Partial<ZevEligibleSources> = {}): ZevEligibleSources => ({
    zev: 'zev-1',
    metering_points: [{ metering_point: 'mp-3', meter_id: 'CH-300', meter_type: 'consumption', eligible_capabilities: ['live'], sources: { history: null, live: null, forecast: null } }],
    connection_point: { available: true, source: null },
    ...overrides,
})

const cleanups: Array<() => void> = []
beforeEach(() => {
    vi.clearAllMocks()
    live.fetchLiveEnabled.mockResolvedValue(true)
    api.fetchEligibleOrNull.mockResolvedValue([])
    api.listSupplementarySources.mockResolvedValue([])
    api.fetchZevEligibleSources.mockResolvedValue(eligibility())
})
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const mount = async (props: { canManage?: boolean } = {}, entry = '/zev-settings/energy') => {
    const view = await renderWithDataRouter(createElement(ZevEnergySources, { zevId: 'zev-1', canManage: props.canManage ?? true }), cleanups, [entry])
    await waitForCondition(() => !view.container.querySelector('.skeleton, [aria-busy="true"]') && view.container.textContent !== '', 'the list')
    for (let tick = 0; tick < 4; tick += 1) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)) })
    return view
}
const press = async (el: Element | null | undefined) => { await act(async () => { (el as HTMLElement).click() }) }
const labels = (root: ParentNode) => Array.from(root.querySelectorAll('[role="group"] button')).map((b) => b.textContent)
const open = async (view: { container: HTMLElement }, id: string) => {
    await press(view.container.querySelector(`[data-source-open="${id}"]`))
    await waitForCondition(() => view.container.querySelector('.detail-pane') !== null, 'the pane')
}

describe('ZevEnergySources', () => {
    it('lists every source of the community, the grid connection point first, with the holder and only a problem coloured', async () => {
        api.listSupplementarySources.mockResolvedValue([
            participantSource(), zevSource({ live_state: 'stale' }), connectionSource(), { ...zevSource({ id: 'other' }), zev: 'zev-9' },
        ])
        const { container } = await mount()

        const rows = Array.from(container.querySelectorAll('.source-row'))
        expect(rows.map((row) => row.querySelector('strong')!.textContent)).toEqual(['live.points.connection', 'CH-100', 'CH-200'])
        expect(rows[1].textContent).toContain('Pia Muster')
        expect(rows[2].textContent).toContain('live.points.zevOperated')
        // A working source says nothing; the quiet one names its problem, as text.
        expect(rows[0].querySelector('.issue-text')).toBeNull()
        expect(rows[2].querySelector('.issue-text--warning')!.textContent).toBe('live.state.stale')
        expect(container.querySelector('.badge')).toBeNull()
    })

    it('offers a manager a primary to connect, and says when there is nothing left to connect', async () => {
        api.listSupplementarySources.mockResolvedValue([zevSource()])
        const connectable = await mount()
        const primary = Array.from(connectable.container.querySelectorAll('button')).find((b) => b.textContent === 'supplementary.zev.connect')!
        expect(primary.disabled).toBe(false)
        // The toolbar returns with the first source, with the intro.
        expect(connectable.container.textContent).toContain('supplementary.zev.description')
        cleanups.splice(0).forEach((cleanup) => cleanup())

        api.fetchZevEligibleSources.mockResolvedValue(eligibility({ metering_points: [], connection_point: { available: false, source: 'src-cp' } }))
        const none = await mount()
        expect(Array.from(none.container.querySelectorAll('button')).find((b) => b.textContent === 'supplementary.zev.connect')!.disabled).toBe(true)
        expect(none.container.textContent).toContain('supplementary.zev.nothingToConnect')
    })

    it('says there is nothing to connect, without a dead button, when the empty community has nothing it could connect', async () => {
        api.fetchZevEligibleSources.mockResolvedValue(eligibility({ metering_points: [], connection_point: { available: false, source: null } }))
        const { container } = await mount()

        expect(container.textContent).toContain('supplementary.zev.empty.nothing')
        expect(Array.from(container.querySelectorAll('button')).some((b) => b.textContent === 'supplementary.zev.connect')).toBe(false)
    })

    it('has an empty state, and a viewer cannot connect anything', async () => {
        const manager = await mount()
        expect(manager.container.textContent).toContain('supplementary.zev.empty.title')
        expect(manager.container.textContent).toContain('supplementary.zev.empty.manager')
        // One explanation and one primary action while the list is empty: no intro above, no second connect button.
        expect(manager.container.textContent).not.toContain('supplementary.zev.description')
        expect(Array.from(manager.container.querySelectorAll('button')).filter((b) => b.textContent === 'supplementary.zev.connect')).toHaveLength(1)
        expect(manager.container.querySelector('.empty-state button')?.textContent).toBe('supplementary.zev.connect')
        cleanups.splice(0).forEach((cleanup) => cleanup())
        api.fetchZevEligibleSources.mockClear()

        const viewer = await mount({ canManage: false })
        expect(viewer.container.textContent).toContain('supplementary.zev.empty.other')
        expect(viewer.container.textContent).not.toContain('supplementary.zev.descriptionReadOnly')
        expect(Array.from(viewer.container.querySelectorAll('button')).some((b) => b.textContent === 'supplementary.zev.connect')).toBe(false)
        expect(api.fetchZevEligibleSources).not.toHaveBeenCalled()
    })

    it('opens a source of the community beside the list with every action of its owner', async () => {
        api.listSupplementarySources.mockResolvedValue([zevSource()])
        const view = await mount()
        await open(view, 'src-zev')

        expect(view.router.state.location.search).toBe('?source=src-zev')
        expect(labels(view.container)).toEqual(expect.arrayContaining([
            'supplementary.actions.rotate', 'supplementary.live.revoke', 'supplementary.actions.disconnect', 'supplementary.actions.remove',
        ]))
        expect(view.container.querySelector('[role="group"]')!.parentElement!.textContent).not.toContain('supplementary.owner.readOnlyNote')
    })

    it('lets a manager only switch off, delete the data of and remove a participant\'s source, never reach its account', async () => {
        api.listSupplementarySources.mockResolvedValue([participantSource()])
        api.updateSupplementarySource.mockResolvedValue(participantSource({ enabled: false }))
        const view = await mount()
        await open(view, 'src-part')

        expect(view.container.querySelector('.detail-pane')!.textContent).toContain('supplementary.owner.readOnlyNote{"name":"Pia Muster"}')
        expect(labels(view.container)).toEqual(['supplementary.owner.disable', 'supplementary.actions.deleteData', 'supplementary.actions.remove'])
        // No sync, test, key or token: the account is the participant's.
        expect(view.container.querySelector('.detail-pane')!.textContent).not.toContain('ABC123')
        expect(view.container.querySelector('input[type="password"]')).toBeNull()

        await press(Array.from(view.container.querySelectorAll('[role="group"] button')).find((b) => b.textContent === 'supplementary.owner.disable'))
        await waitForCondition(() => api.updateSupplementarySource.mock.calls.length === 1, 'the switch-off')
        expect(api.updateSupplementarySource).toHaveBeenCalledWith('src-part', { enabled: false })
    })

    it('says where participants connect their own, as a link only for a manager who has that page', async () => {
        // No meter of their own: the place is named in plain text, because the manager cannot go there.
        const plain = await mount()
        expect(plain.container.querySelector('.empty-state')?.textContent).toContain('supplementary.zev.participantsOwn')
        expect(plain.container.querySelector('.empty-state a')).toBeNull()
        cleanups.splice(0).forEach((cleanup) => cleanup())

        // A meter of their own: the sentence is followed by the link.
        api.fetchEligibleOrNull.mockResolvedValue([{ metering_point: 'mp-1', meter_id: 'CH-100', zev: 'zev-1', zev_name: 'Sonnenhof', participant: 'p-1', source: null, eligible_capabilities: ['live'] }])
        const linked = await mount()
        expect(linked.container.querySelector('.empty-state')?.textContent).toContain('supplementary.zev.participantsOwnSelf')
        expect(linked.container.querySelector('.empty-state a')?.getAttribute('href')).toBe('/me/metering-points')
        cleanups.splice(0).forEach((cleanup) => cleanup())

        // With sources listed it sits in the intro; a viewer is told nothing about it.
        api.listSupplementarySources.mockResolvedValue([zevSource()])
        const listed = await mount()
        expect(listed.container.querySelector('.energy-sources-intro a')?.getAttribute('href')).toBe('/me/metering-points')
        cleanups.splice(0).forEach((cleanup) => cleanup())
        const viewer = await mount({ canManage: false })
        expect(viewer.container.querySelector('.energy-sources-intro')?.textContent).not.toContain('participantsOwn')
        expect(viewer.container.querySelector('a')).toBeNull()
    })

    it('points a manager who holds the meter themselves to My metering points', async () => {
        api.listSupplementarySources.mockResolvedValue([participantSource()])
        api.fetchEligibleOrNull.mockResolvedValue([{ metering_point: 'mp-1', meter_id: 'CH-100', zev: 'zev-1', zev_name: 'Sonnenhof', participant: 'p-1', source: 'src-part', eligible_capabilities: ['history', 'live'] }])
        const view = await mount()
        await open(view, 'src-part')

        expect(view.container.querySelector('.detail-pane a')?.getAttribute('href')).toBe('/me/metering-points')
    })

    it('shows a viewer a source read-only, with no action at all', async () => {
        api.listSupplementarySources.mockResolvedValue([participantSource()])
        const view = await mount({ canManage: false })
        await open(view, 'src-part')

        expect(view.container.querySelector('[role="group"]')).toBeNull()
        expect(view.container.querySelector('.detail-pane')).not.toBeNull()
    })

    it('reopens a source from a link, and X takes it away', async () => {
        api.listSupplementarySources.mockResolvedValue([zevSource()])
        const view = await mount({}, '/zev-settings/energy?source=src-zev')
        await waitForCondition(() => view.container.querySelector('.detail-pane') !== null, 'the pane')

        await press(view.container.querySelector('.detail-pane header button'))
        expect(view.container.querySelector('.detail-pane')).toBeNull()
        expect(view.router.state.location.search).toBe('')
    })
})

describe('connecting a source for the community', () => {
    const openDialog = async (view: { container: HTMLElement }) => {
        await press(Array.from(view.container.querySelectorAll('button')).find((b) => b.textContent === 'supplementary.zev.connect'))
        await waitForCondition(() => document.querySelector('[role="dialog"]') !== null, 'the dialog')
        return document.querySelector<HTMLElement>('[role="dialog"]')!
    }

    it('offers the grid connection point and every meter nobody holds, with what each can still provide', async () => {
        api.listSupplementarySources.mockResolvedValue([zevSource()])
        const dialog = await openDialog(await mount())

        const options = Array.from(dialog.querySelectorAll('option')).map((option) => option.textContent)
        expect(options).toEqual(['supplementary.zev.pickTarget', 'live.points.connection', 'CH-300 · supplementary.capability.live'])
        // Until something is chosen the dialog says what comes next, instead of showing only Cancel.
        expect(dialog.textContent).toContain('supplementary.zev.pickHint')
    })

    it('connects the grid connection point through its own flow', async () => {
        api.listSupplementarySources.mockResolvedValue([zevSource()])
        const dialog = await openDialog(await mount())
        const select = dialog.querySelector('select')!
        await act(async () => {
            const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
            setter.call(select, 'connection-point')
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await press(Array.from(dialog.querySelectorAll('button')).find((b) => b.textContent === 'supplementary.connection.connect'))

        await waitForCondition(() => (document.querySelector('[role="dialog"]')?.textContent ?? '').includes('supplementary.consent.connectionPoint'), 'the connection point flow')
    })

    it('opens the source it has just connected beside the list', async () => {
        api.listSupplementarySources.mockResolvedValue([zevSource()])
        api.fetchZevEligibleSources.mockResolvedValue(eligibility({ connection_point: { available: false, source: null } }))
        const created = zevSource({ id: 'src-new', metering_point: 'mp-3', metering_point_meter_id: 'CH-300', push_token_prefix: null })
        api.createSupplementarySource.mockResolvedValue({ ...created, push_token: undefined })
        const view = await mount()
        const dialog = await openDialog(view)
        // One meter is the only target, so it is chosen already; connect its live data.
        const connect = Array.from(dialog.querySelectorAll('button')).find((b) => b.textContent === 'supplementary.card.connectRow')!
        await press(connect)
        const modal = document.querySelector<HTMLElement>('[role="dialog"]')!
        await press(modal.querySelector('input[type="checkbox"]'))
        api.listSupplementarySources.mockResolvedValue([zevSource(), created])
        await press(Array.from(modal.querySelectorAll('button')).find((b) => b.textContent === 'supplementary.modal.connect'))

        await waitForCondition(() => view.router.state.location.search === '?source=src-new', 'the new source to open')
        expect(api.createSupplementarySource).toHaveBeenCalledWith(expect.objectContaining({ held_by: 'zev', metering_point: 'mp-3', provides_live: true, provides_history: false }))
    })
})
