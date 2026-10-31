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
    coverage: { producing_points: 1, producing_fresh: 1, consuming_points: 6, consuming_fresh: 1, connection_point: 'fresh', live_sources: liveSources },
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
})

describe('LiveEnergyView', () => {
    it('says so, and never asks for the snapshot, while the feature is off', async () => {
        api.fetchLiveEnabled.mockResolvedValue(false)
        const { container } = await render()

        expect(container.textContent).toContain('pages.live.disabled')
        expect(api.fetchLiveSnapshotOrNull).not.toHaveBeenCalled()
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
        [true, '/metering/points', 'pages.live.empty.manager'],
        [false, '/me/metering-points', 'pages.live.empty.participant'],
    ])('without a live source a manager (%s) is pointed to %s', async (isZevScope, href, text) => {
        mockAccess.mockReturnValue({ isZevScope })
        api.fetchLiveSnapshotOrNull.mockResolvedValue(snapshot(0))
        const { container } = await render()

        expect(container.textContent).toContain(text)
        expect(container.querySelector('.empty-state a')?.getAttribute('href')).toBe(href)
        expect(api.fetchLiveCurveOrNull).not.toHaveBeenCalled()
    })

    it('shows the card, and the points table for a manager, when live sources exist', async () => {
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
        expect(api.fetchLiveCurveOrNull).toHaveBeenCalled()
    })
})
