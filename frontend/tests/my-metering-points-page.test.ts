import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MyMeteringPointsPage } from '../src/pages/MyMeteringPointsPage'
import type { EligibleMeteringPoint, MeteringPoint } from '../src/types/api'
import { queryKeys } from '../src/lib/api/queryKeys'
import { renderWithProviders } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: actual.DEFAULT_APP_SETTINGS, isLoading: false }) }
})

const access = vi.hoisted(() => ({ participantScope: true }))
vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => ({ selectedZevId: 'zev-1', selectedZev: { id: 'zev-1', name: 'Sonnenhof' }, entries: [] }),
}))
vi.mock('../src/lib/communityAccess', () => ({
    useCommunityAccess: () => ({ isParticipantScope: access.participantScope }),
    useScopeNote: () => undefined,
}))
// The scope guard is its own concern; the page under test is the content behind it.
vi.mock('../src/components/ScopeGuard', () => ({ ScopeGuard: ({ children }: { children: unknown }) => children }))

const api = vi.hoisted(() => ({
    fetchMeteringPoints: vi.fn(),
    listSupplementarySources: vi.fn(),
    fetchEligibleOrNull: vi.fn(),
}))
vi.mock('../src/lib/api/zev', () => ({ fetchMeteringPoints: api.fetchMeteringPoints }))
vi.mock('../src/lib/api/supplementary', () => ({
    listSupplementarySources: api.listSupplementarySources,
    fetchEligibleOrNull: api.fetchEligibleOrNull,
}))
// The connected-source card and the connect modal have their own tests.
vi.mock('../src/features/supplementary/MeteringPointEnergyData', () => ({
    MeteringPointEnergyData: ({ point, sourcesUnavailable }: { point: EligibleMeteringPoint; sourcesUnavailable?: string }) =>
        createElement('article', { 'data-testid': 'energy-data', 'data-unavailable': sourcesUnavailable ?? '' }, `energy:${point.meter_id}`),
}))

const point = (id: string, flagged: boolean): MeteringPoint => ({
    id, zev: 'zev-1', meter_id: `CH-${id}`, meter_type: 'bidirectional', is_active: true, building: 'b-1', building_name: 'Haus',
    has_behind_meter_generation: flagged, reading_count: 0, assignment_count: 1, first_reading_at: null, last_reading_at: null,
    supplementary_source_status: null,
})
const eligible = (id: string, zev = 'zev-1'): EligibleMeteringPoint => ({
    metering_point: id, meter_id: `CH-${id}`, zev, zev_name: 'Sonnenhof', participant: 'p-1', source: null,
})

const cleanups: Array<() => void> = []
beforeEach(() => {
    vi.clearAllMocks()
    access.participantScope = true
    api.fetchMeteringPoints.mockResolvedValue([point('1', true), point('2', false), point('3', true)])
    api.listSupplementarySources.mockResolvedValue([])
    api.fetchEligibleOrNull.mockResolvedValue([eligible('1')])
})
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function mount() {
    const view = await renderWithProviders(createElement(MyMeteringPointsPage), cleanups)
    await waitForCondition(() => /CH-|myMeteringPoints\.empty/.test(view.container.textContent ?? ''), 'the page content')
    return view
}

describe('MyMeteringPointsPage', () => {
    it('puts the energy data on the meter the participant holds, and lists the others plainly', async () => {
        const { container } = await mount()

        const energy = container.querySelectorAll('[data-testid="energy-data"]')
        expect(energy).toHaveLength(1)
        expect(energy[0].textContent).toBe('energy:CH-1')
        expect(container.querySelector('article[aria-label="CH-2"]')).not.toBeNull()
        expect(container.querySelector('article[aria-label="CH-3"]')).not.toBeNull()
    })

    it('links every plain meter to its metering data', async () => {
        const { container } = await mount()

        const href = (label: string) => container.querySelector(`article[aria-label="${label}"] a`)?.getAttribute('href')
        expect(href('CH-2')).toBe('/metering/chart?metering_point=2')
        expect(href('CH-3')).toBe('/metering/chart?metering_point=3')
    })

    it('explains why a flagged meter the participant does not hold personally has no energy data', async () => {
        const { container } = await mount()

        expect(container.querySelector('article[aria-label="CH-3"]')!.textContent).toContain('pages.myMeteringPoints.notHolder')
        expect(container.querySelector('article[aria-label="CH-2"]')!.textContent).not.toContain('pages.myMeteringPoints.notHolder')
    })

    it('tells the participant who to ask to flag a meter', async () => {
        const { container } = await mount()

        expect(container.textContent).toContain('pages.myMeteringPoints.flagHint')
        expect(container.textContent).toContain('supplementary.section.description')
    })

    it('says nothing about energy data while the feature is off', async () => {
        api.fetchEligibleOrNull.mockResolvedValue(null)
        const { container } = await mount()

        expect(container.querySelectorAll('article')).toHaveLength(3)
        expect(container.querySelector('[data-testid="energy-data"]')).toBeNull()
        expect(container.textContent).not.toContain('pages.myMeteringPoints.flagHint')
        expect(container.textContent).not.toContain('pages.myMeteringPoints.notHolder')
        expect(container.textContent).not.toContain('supplementary.section.description')
        expect(api.listSupplementarySources).not.toHaveBeenCalled()
    })

    it('shows only the energy data of the selected community', async () => {
        api.fetchEligibleOrNull.mockResolvedValue([eligible('1'), eligible('9', 'zev-2')])
        const { container } = await mount()

        expect(container.querySelectorAll('[data-testid="energy-data"]')).toHaveLength(1)
        expect(container.textContent).not.toContain('CH-9')
    })

    it('shows a manager only the meters they hold themselves, not the community\'s list', async () => {
        access.participantScope = false
        const { container } = await mount()

        expect(api.fetchMeteringPoints).not.toHaveBeenCalled()
        expect(container.querySelectorAll('[data-testid="energy-data"]')).toHaveLength(1)
        expect(container.querySelector('article[aria-label="CH-2"]')).toBeNull()
        expect(container.textContent).not.toContain('pages.myMeteringPoints.flagHint')
    })

    it('ignores the community list the metering points page left in the cache, for a manager', async () => {
        access.participantScope = false
        const { container, client } = await mount()

        await act(async () => {
            client.setQueryData(queryKeys.metering.points('zev-1'), [point('1', true), point('2', false), point('3', true)])
            await new Promise((resolve) => setTimeout(resolve, 20))
        })

        expect(container.querySelectorAll('article')).toHaveLength(1)
        expect(container.querySelector('article[aria-label="CH-2"]')).toBeNull()
    })

    it('does not let the metering points page\'s failed list request replace a manager\'s own meters', async () => {
        access.participantScope = false
        const { container, client } = await mount()

        await act(async () => {
            await client.fetchQuery({ queryKey: queryKeys.metering.points('zev-1'), queryFn: () => Promise.reject(new Error('boom')), retry: false }).catch(() => undefined)
        })

        expect(container.querySelectorAll('[data-testid="energy-data"]')).toHaveLength(1)
        expect(container.textContent).not.toContain('pages.myMeteringPoints.loadFailed')
    })

    it('still reports a failed list request to a participant', async () => {
        api.fetchMeteringPoints.mockRejectedValue(new Error('boom'))
        const view = await renderWithProviders(createElement(MyMeteringPointsPage), cleanups)
        await waitForCondition(() => (view.container.textContent ?? '').includes('pages.myMeteringPoints.loadFailed'), 'the error')
    })

    it('reports a failed eligibility check instead of reading it as the feature being off, and can retry', async () => {
        api.fetchEligibleOrNull.mockRejectedValueOnce(new Error('boom'))
        const view = await renderWithProviders(createElement(MyMeteringPointsPage), cleanups)
        await waitForCondition(() => (view.container.textContent ?? '').includes('supplementary.section.eligibilityError'), 'the error')

        expect(view.container.textContent).not.toContain('pages.myMeteringPoints.empty')
        expect(view.container.querySelector('article')).toBeNull()

        await act(async () => { Array.from(view.container.querySelectorAll('button')).find((b) => b.textContent?.includes('common.retry'))?.click() })
        await waitForCondition(() => view.container.querySelector('[data-testid="energy-data"]') !== null, 'the page after the retry')
    })

    it.each([
        ['is still loading', () => new Promise(() => undefined), 'loading'],
        ['failed', () => Promise.reject(new Error('boom')), 'error'],
    ])('tells the card when the source list %s, so it cannot offer Connect for a meter that has a source', async (_label, pending, expected) => {
        api.fetchEligibleOrNull.mockResolvedValue([{ ...eligible('1'), source: 'src-1' }])
        api.listSupplementarySources.mockImplementation(pending)
        const { container } = await mount()
        await waitForCondition(() => container.querySelector('[data-testid="energy-data"]')?.getAttribute('data-unavailable') === expected, `the ${expected} state`)
    })

    it('has a sensible empty state for each audience', async () => {
        api.fetchMeteringPoints.mockResolvedValue([])
        api.fetchEligibleOrNull.mockResolvedValue([])
        const participant = await mount()
        expect(participant.container.textContent).toContain('pages.myMeteringPoints.empty.participant')

        access.participantScope = false
        const manager = await mount()
        expect(manager.container.textContent).toContain('pages.myMeteringPoints.empty.manager')
    })
})
