import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LiveEnergyView } from '../src/features/live/LiveEnergyView'
import type { LiveSnapshot } from '../src/types/api'
import { renderWithProviders } from './helpers/render'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, options?: Record<string, unknown>) => (options ? `${key}|${JSON.stringify(options)}` : key),
    }),
}))

const mockAccess = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/communityAccess', () => ({ useCommunityAccess: () => mockAccess() }))

const api = vi.hoisted(() => ({
    fetchLiveEnabled: vi.fn(),
    fetchLiveSnapshotOrNull: vi.fn(),
    fetchLiveCurveOrNull: vi.fn(),
}))
vi.mock('../src/lib/api/live', () => api)

const eligibleApi = vi.hoisted(() => ({ fetchEligibleOrNull: vi.fn(), listSupplementarySources: vi.fn() }))
vi.mock('../src/lib/api/supplementary', () => eligibleApi)

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const snapshot = (liveSources: number, overrides: Partial<LiveSnapshot> = {}): LiveSnapshot => ({
    zev_id: 'z1',
    as_of: '2026-10-30T11:02:10Z',
    tier: 'exact',
    consumption_basis: 'connection_point',
    production_w: 8000,
    consumption_w: 5000,
    surplus_w: 3000,
    grid_import_w: 0,
    local_share_pct: 100,
    coverage: { producing_points: 1, producing_fresh: 1, consuming_points: 6, consuming_fresh: 1, connection_point: 'fresh', live_sources: liveSources, points: 7, points_fresh: 2 },
    own: null,
    max_age_s: 60,
    ...overrides,
} as LiveSnapshot)

async function render() {
    const rendered = await renderWithProviders(createElement(LiveEnergyView, { zevId: 'z1' }), cleanups)
    // The flag, then the snapshot, then the curve: let each query settle.
    for (let tick = 0; tick < 4; tick += 1) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)) })
    return rendered
}

beforeEach(() => {
    vi.clearAllMocks()
    mockAccess.mockReturnValue({ isZevScope: true })
    api.fetchLiveEnabled.mockResolvedValue(true)
    api.fetchLiveCurveOrNull.mockResolvedValue(null)
    api.fetchLiveSnapshotOrNull.mockResolvedValue(snapshot(2))
    eligibleApi.fetchEligibleOrNull.mockResolvedValue([])
})

describe('LiveEnergyView', () => {
    it('says so while the feature is off, whatever the snapshot answered', async () => {
        api.fetchLiveEnabled.mockResolvedValue(false)
        // The snapshot is asked without waiting for the flag; while the feature is off the server answers 404.
        api.fetchLiveSnapshotOrNull.mockResolvedValue(null)
        const { container } = await render()

        expect(container.textContent).toContain('pages.live.disabled')
    })

    it('asks for the snapshot at once, without waiting for the flag', async () => {
        api.fetchLiveEnabled.mockReturnValue(new Promise(() => {}))
        await render()

        expect(api.fetchLiveSnapshotOrNull).toHaveBeenCalledWith('z1')
    })

    it('says so when the server does not show the ZEV to the caller', async () => {
        api.fetchLiveSnapshotOrNull.mockResolvedValue(null)
        const { container } = await render()

        expect(container.textContent).toContain('pages.live.unavailable')
    })

    it('offers a retry when the snapshot fails', async () => {
        api.fetchLiveSnapshotOrNull.mockRejectedValue(new Error('boom'))
        const { container } = await render()

        expect(container.textContent).toContain('pages.live.loadFailed')
        expect(container.querySelector('.card.error-banner button')).not.toBeNull()
    })

    it.each([
        [{ isZevScope: true, canManage: true }, '/zev-settings/energy', 'pages.live.empty.manager', 'pages.live.empty.managerAction'],
        [{ isZevScope: false, canManage: false }, '/me/metering-points', 'pages.live.empty.participant', 'pages.live.empty.participantAction'],
    ])('without a live source %j is pointed to %s', async (access, href, text, action) => {
        mockAccess.mockReturnValue(access)
        api.fetchLiveSnapshotOrNull.mockResolvedValue(snapshot(0))
        const { container } = await render()

        expect(container.textContent).toContain(text)
        expect(container.querySelector('.empty-state a')?.getAttribute('href')).toBe(href)
        expect(container.querySelector('.empty-state a')?.textContent).toBe(action)
        expect(api.fetchLiveCurveOrNull).not.toHaveBeenCalled()
    })

    it('tells a viewer who can connect a source instead of offering a button they cannot use', async () => {
        mockAccess.mockReturnValue({ isZevScope: true, canManage: false })
        api.fetchLiveSnapshotOrNull.mockResolvedValue(snapshot(0))
        const { container } = await render()

        expect(container.textContent).toContain('pages.live.empty.viewer')
        expect(container.querySelector('.empty-state a, .empty-state button')).toBeNull()
    })

    it('shows the card, and the points table for a manager, when live sources exist, without the curve', async () => {
        api.fetchLiveSnapshotOrNull.mockResolvedValue(snapshot(2, {
            points: [{
                metering_point_id: 'm1', target: 'metering_point', meter_id: 'CH-1', meter_type: 'consumption',
                participant_name: 'Anna', held_by: 'participant', live_state: 'fresh', meter_power_w: 1200, age_s: 7, source_id: 's1',
            }],
        }))
        const { container } = await render()

        expect(container.textContent).toContain('live.title')
        expect(container.textContent).toContain('CH-1')
        expect(container.querySelector('.empty-state')).toBeNull()
        expect(api.fetchLiveCurveOrNull).not.toHaveBeenCalled() // the curve belongs to the Today view now
    })

    describe('for a participant whose own meter reports nothing', () => {
        const meter = (live: string | null) => ({
            metering_point: 'mp', meter_id: 'CH-1', zev: 'z1', zev_name: 'Z1', participant: 'p1', source: null,
            eligible_capabilities: ['live'], sources: { history: null, live, forecast: null },
        })

        beforeEach(() => mockAccess.mockReturnValue({ isZevScope: false, canManage: false }))

        it('says why the own figures are missing and links to where a live source is connected', async () => {
            eligibleApi.fetchEligibleOrNull.mockResolvedValue([meter(null)])
            const { container } = await render()

            expect(container.textContent).toContain('myEnergy.noLiveSource')
            expect(container.querySelector('a[href="/me/metering-points"]')?.textContent).toBe('myEnergy.connectLive')
        })

        it('stays quiet when a source exists, when the meter cannot host one, and for a manager', async () => {
            eligibleApi.fetchEligibleOrNull.mockResolvedValue([meter('s1')])
            expect((await render()).container.textContent).not.toContain('myEnergy.noLiveSource')
            cleanups.splice(0).forEach((cleanup) => cleanup())

            eligibleApi.fetchEligibleOrNull.mockResolvedValue([])
            expect((await render()).container.textContent).not.toContain('myEnergy.noLiveSource')
            cleanups.splice(0).forEach((cleanup) => cleanup())

            mockAccess.mockReturnValue({ isZevScope: true, canManage: true })
            eligibleApi.fetchEligibleOrNull.mockResolvedValue([meter(null)])
            expect((await render()).container.textContent).not.toContain('myEnergy.noLiveSource')
        })
    })
})
