import { createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MyMeteringPointsPage } from '../src/pages/MyMeteringPointsPage'
import type { EligibleMeteringPoint, MeteringPoint } from '../src/types/api'
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
    MeteringPointEnergyData: ({ point }: { point: EligibleMeteringPoint }) => createElement('article', { 'data-testid': 'energy-data' }, `energy:${point.meter_id}`),
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
