import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useEnergyDataEligibility } from '../src/lib/supplementary'
import type { EligibleMeteringPoint } from '../src/types/api'
import { renderWithProviders } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

const api = vi.hoisted(() => ({ fetchEligibleOrNull: vi.fn() }))
vi.mock('../src/lib/api/supplementary', () => api)

const held = (id: string, capabilities?: EligibleMeteringPoint['eligible_capabilities']): EligibleMeteringPoint => ({
    metering_point: id, meter_id: `CH-${id}`, zev: 'zev-1', zev_name: 'Sonnenhof', participant: 'p-1', source: null,
    ...(capabilities ? { eligible_capabilities: capabilities } : {}),
})

const cleanups: Array<() => void> = []
beforeEach(() => vi.clearAllMocks())
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function read() {
    let result: ReturnType<typeof useEnergyDataEligibility> | undefined
    function Probe() {
        result = useEnergyDataEligibility()
        return null
    }
    await renderWithProviders(createElement(Probe), cleanups)
    await waitForCondition(() => result !== undefined && !result.isLoading, 'the eligibility')
    await act(async () => undefined)
    return result!
}

describe('useEnergyDataEligibility with the live flag on', () => {
    it('does not treat a plain consumption meter as a behind-meter point', async () => {
        api.fetchEligibleOrNull.mockResolvedValue([held('1', ['live'])])
        const eligibility = await read()

        expect(eligibility.featureOn).toBe(true)
        expect(eligibility.eligible).toHaveLength(1)
        expect(eligibility.historyEligible).toEqual([])
        expect(eligibility.liveEligible).toHaveLength(1)
        // Drives the "show your real self-sufficiency" call to action: nothing to connect for history.
        expect(eligibility.canConnect).toBe(false)
    })

    it('keeps a behind-meter point as history-eligible next to the live ones', async () => {
        api.fetchEligibleOrNull.mockResolvedValue([held('1', ['live']), held('2', ['history', 'live'])])
        const eligibility = await read()

        expect(eligibility.historyEligible.map((point) => point.metering_point)).toEqual(['2'])
        expect(eligibility.liveEligible).toHaveLength(2)
        expect(eligibility.canConnect).toBe(true)
    })
})

describe('useEnergyDataEligibility with the live flag off', () => {
    it('lists behind-meter points only, without capabilities, and all of them are history-eligible', async () => {
        api.fetchEligibleOrNull.mockResolvedValue([held('1')])
        const eligibility = await read()

        expect(eligibility.historyEligible).toHaveLength(1)
        expect(eligibility.liveEligible).toEqual([])
        expect(eligibility.canConnect).toBe(true)
    })

    it('is off when the energy data feature is off', async () => {
        api.fetchEligibleOrNull.mockResolvedValue(null)
        const eligibility = await read()

        expect(eligibility.featureOn).toBe(false)
        expect(eligibility.canConnect).toBe(false)
    })
})
