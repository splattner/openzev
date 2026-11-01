import { AxiosError } from 'axios'
import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProductionForecastChart } from '../src/features/live/ProductionForecastChart'
import { PvPlanesDialog } from '../src/features/meteringPoints/PvPlanesDialog'
import { ForecastConnectDialog } from '../src/features/supplementary/ForecastConnectDialog'
import type { Building, MeteringPoint, ProductionForecast, PvPlane, SupplementarySource } from '../src/types/api'
import { renderWithProviders, setInputValue } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key}${JSON.stringify(options)}` : key) }),
}))
// The chart library measures the DOM, which a test renderer does not have.
vi.mock('recharts', () => {
    const passthrough = ({ children }: { children?: unknown }) => children ?? null
    return {
        ResponsiveContainer: passthrough, ComposedChart: ({ data }: { data: unknown[] }) => `chart:${data.length}`,
        Area: () => null, Bar: () => null, CartesianGrid: () => null, Tooltip: () => null, XAxis: () => null, YAxis: () => null,
    }
})
const pushToast = vi.fn()
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))

const supplementary = vi.hoisted(() => ({ createSupplementarySource: vi.fn(), updateSupplementarySource: vi.fn() }))
vi.mock('../src/lib/api/supplementary', async (importOriginal) => ({ ...(await importOriginal<typeof import('../src/lib/api/supplementary')>()), ...supplementary }))
const zev = vi.hoisted(() => ({ fetchPvPlanes: vi.fn(), createPvPlane: vi.fn(), updatePvPlane: vi.fn(), deletePvPlane: vi.fn() }))
vi.mock('../src/lib/api/zev', async (importOriginal) => ({ ...(await importOriginal<typeof import('../src/lib/api/zev')>()), ...zev }))

const apiError = (data: Record<string, unknown>) =>
    new AxiosError('Bad Request', '400', undefined, undefined, { status: 400, data, statusText: 'Bad Request', headers: {}, config: {} as never })

const forecast = (overrides: Partial<ProductionForecast> = {}): ProductionForecast => ({
    zev_id: 'z1', horizon_h: 72, complete: true, plants: 2, plants_with_forecast: 2, fetched_at: '2026-06-01T08:00:00Z',
    hours: [
        { start: '2026-06-01T10:00:00Z', power_w: 6400, min_w: 5000, max_w: 7000 },
        { start: '2026-06-01T11:00:00Z', power_w: 7400, min_w: null, max_w: null },
    ],
    peak_windows: [{ date: '2099-01-01', from: '2099-01-01T09:00:00Z', to: '2099-01-01T13:00:00Z', peak_w: 7900 }],
    ...overrides,
})

const cleanups: Array<() => void> = []
beforeEach(() => vi.clearAllMocks())
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const buttons = (root: ParentNode) => Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
const buttonWith = (root: ParentNode, label: string) => buttons(root).find((b) => b.textContent?.includes(label))
const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]')

describe('ProductionForecastChart', () => {
    it('says when the plants are expected to produce most, and never that power is spare', async () => {
        const { container } = await renderWithProviders(createElement(ProductionForecastChart, { forecast: forecast() }), cleanups)
        expect(container.textContent).toContain('forecast.title')
        expect(container.textContent).toContain('forecast.peak.date')
        expect(container.textContent).toContain('chart:2')
        expect(container.textContent).toContain('forecast.hint')
        expect(container.textContent).not.toContain('forecast.partial')
    })

    it('says how many plants the sum covers when it is partial', async () => {
        const { container } = await renderWithProviders(
            createElement(ProductionForecastChart, { forecast: forecast({ complete: false, plants_with_forecast: 1 }) }), cleanups,
        )
        expect(container.textContent).toContain('forecast.partial{"count":1,"total":2}')
    })
})

describe('ForecastConnectDialog', () => {
    const point = { metering_point: 'mp-1', meter_id: 'CH-100', zev: 'zev-1' }

    it('connects forecast.solar to a ZEV-operated plant without consent, credentials or a token', async () => {
        supplementary.createSupplementarySource.mockResolvedValue({})
        const onClose = vi.fn()
        await renderWithProviders(createElement(ForecastConnectDialog, { holder: 'zev', point, onClose }), cleanups)
        expect(dialog()!.textContent).toContain('supplementary.forecast.needsManager')
        expect(dialog()!.textContent).not.toContain('supplementary.forecast.solarManagerHint')
        await act(async () => { buttonWith(dialog()!, 'supplementary.forecast.connect')!.click() })

        expect(supplementary.createSupplementarySource).toHaveBeenCalledWith({
            provider: 'forecast_solar', metering_point: 'mp-1', provides_history: false, provides_live: false, provides_forecast: true,
            target: 'metering_point', held_by: 'zev', zev: 'zev-1', consent: false,
        })
        await waitForCondition(() => onClose.mock.calls.length > 0, 'the dialog to close')
        expect(pushToast).toHaveBeenCalledWith('supplementary.forecast.connected', 'success')
    })

    it('connects for a holder as a participant-held source and points to Solar Manager', async () => {
        supplementary.createSupplementarySource.mockResolvedValue({})
        await renderWithProviders(createElement(ForecastConnectDialog, { holder: 'participant', point, onClose: vi.fn() }), cleanups)
        expect(dialog()!.textContent).toContain('supplementary.forecast.solarManagerHint')
        await act(async () => { buttonWith(dialog()!, 'supplementary.forecast.connect')!.click() })
        expect(supplementary.createSupplementarySource.mock.calls[0][0]).toMatchObject({ held_by: 'participant', zev: undefined })
    })

    it('says in its own language who adds the missing roof planes, and stays open', async () => {
        supplementary.createSupplementarySource.mockRejectedValue(apiError({ provides_forecast: ["Add the roof planes of this plant and the building's coordinates first."] }))
        const onClose = vi.fn()
        await renderWithProviders(createElement(ForecastConnectDialog, { holder: 'zev', point, onClose }), cleanups)
        await act(async () => { buttonWith(dialog()!, 'supplementary.forecast.connect')!.click() })
        await waitForCondition(() => dialog()!.textContent?.includes('supplementary.forecast.setupMissingManager') === true, 'the translated refusal')
        expect(dialog()!.textContent).not.toContain('Add the roof planes')
        expect(onClose).not.toHaveBeenCalled()
    })

    it('tells a participant to ask the management, and shows any other refusal as the server words it', async () => {
        supplementary.createSupplementarySource.mockRejectedValueOnce(apiError({ provides_forecast: ["Add the roof planes of this plant and the building's coordinates first."] }))
        await renderWithProviders(createElement(ForecastConnectDialog, { holder: 'participant', point, onClose: vi.fn() }), cleanups)
        await act(async () => { buttonWith(dialog()!, 'supplementary.forecast.connect')!.click() })
        await waitForCondition(() => dialog()!.textContent?.includes('supplementary.forecast.setupMissingParticipant') === true, 'the participant text')

        supplementary.createSupplementarySource.mockRejectedValueOnce(apiError({ provides_forecast: ['Live energy data is not enabled.'] }))
        await act(async () => { buttonWith(dialog()!, 'supplementary.forecast.connect')!.click() })
        await waitForCondition(() => dialog()!.textContent?.includes('Live energy data is not enabled.') === true, 'the server message')
    })
})

describe('ForecastConnectDialog with a Solar Manager connection', () => {
    const point = { metering_point: 'mp-1', meter_id: 'CH-100', zev: 'zev-1' }
    const solarManager = (overrides: Partial<SupplementarySource> = {}) =>
        ({
            id: 'sm-1', metering_point: 'mp-1', provider: 'solar_manager', held_by: 'participant', enabled: true, has_credential: true,
            status: 'ok', provides_forecast: false, ...overrides,
        }) as SupplementarySource
    const open = (sources: SupplementarySource[]) =>
        renderWithProviders(createElement(ForecastConnectDialog, { holder: 'participant', point, sources, onClose: vi.fn() }), cleanups)
    const radios = () => Array.from(dialog()!.querySelectorAll<HTMLInputElement>('input[type="radio"]'))

    it('offers the existing connection first and switches its forecast on with consent, without a new source', async () => {
        supplementary.updateSupplementarySource.mockResolvedValue({})
        await open([solarManager()])
        expect(radios()).toHaveLength(2)
        expect(radios()[0].checked).toBe(true)
        const connect = buttonWith(dialog()!, 'supplementary.forecast.connect')!
        expect(connect.disabled).toBe(true)
        await act(async () => { dialog()!.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click() })
        await act(async () => { connect.click() })

        expect(supplementary.updateSupplementarySource).toHaveBeenCalledWith('sm-1', { provides_forecast: true, consent: true })
        expect(supplementary.createSupplementarySource).not.toHaveBeenCalled()
    })

    it('still lets the holder pick forecast.solar instead', async () => {
        supplementary.createSupplementarySource.mockResolvedValue({})
        await open([solarManager()])
        await act(async () => { radios()[1].click() })
        expect(dialog()!.querySelector('input[type="checkbox"]')).toBeNull()
        await act(async () => { buttonWith(dialog()!, 'supplementary.forecast.connect')!.click() })
        expect(supplementary.createSupplementarySource).toHaveBeenCalledOnce()
        expect(supplementary.updateSupplementarySource).not.toHaveBeenCalled()
    })

    it('offers nothing extra when the connection cannot read a forecast', async () => {
        for (const broken of [{ enabled: false }, { has_credential: false }, { status: 'reconnect_required' as const }, { provides_forecast: true }, { provider: 'push' as const }]) {
            await open([solarManager(broken)])
            expect(radios(), JSON.stringify(broken)).toHaveLength(0)
            cleanups.splice(0).forEach((cleanup) => cleanup())
        }
    })
})

describe('PvPlanesDialog', () => {
    const point = { id: 'mp-1', meter_id: 'CH-100', meter_type: 'production' } as MeteringPoint
    const plane = (overrides: Partial<PvPlane> = {}): PvPlane => ({
        id: 'pl-1', metering_point: 'mp-1', label: 'South', peak_power_kwp: '8.50', tilt_deg: 30, azimuth_deg: 0,
        created_at: '', updated_at: '', ...overrides,
    })

    it('lists the planes with their direction', async () => {
        zev.fetchPvPlanes.mockResolvedValue([plane(), plane({ id: 'pl-2', label: 'West', azimuth_deg: 90 })])
        await renderWithProviders(createElement(PvPlanesDialog, { point, canWrite: true, onClose: vi.fn() }), cleanups)
        await waitForCondition(() => dialog()!.textContent?.includes('South') === true, 'the planes')
        expect(dialog()!.textContent).toContain('"direction":"pages.meteringPoints.planes.direction.west"')
    })

    it('adds a plane from the form', async () => {
        zev.fetchPvPlanes.mockResolvedValue([])
        zev.createPvPlane.mockResolvedValue(plane())
        await renderWithProviders(createElement(PvPlanesDialog, { point, canWrite: true, onClose: vi.fn() }), cleanups)
        await waitForCondition(() => dialog()!.textContent?.includes('pages.meteringPoints.planes.empty') === true, 'the empty state')
        await act(async () => { buttonWith(dialog()!, 'pages.meteringPoints.planes.add')!.click() })
        const inputs = Array.from(dialog()!.querySelectorAll<HTMLInputElement>('input'))
        await act(async () => {
            setInputValue(inputs[0], 'South roof')
            setInputValue(inputs[1], '8.5')
            setInputValue(inputs[2], '25')
            setInputValue(inputs[3], '-10')
        })
        await act(async () => { dialog()!.querySelector('form')!.requestSubmit() })

        expect(zev.createPvPlane).toHaveBeenCalledWith('mp-1', { label: 'South roof', peak_power_kwp: '8.50', tilt_deg: 25, azimuth_deg: -10 })
    })

    it('refuses an impossible value before asking the server', async () => {
        zev.fetchPvPlanes.mockResolvedValue([])
        await renderWithProviders(createElement(PvPlanesDialog, { point, canWrite: true, onClose: vi.fn() }), cleanups)
        await waitForCondition(() => dialog()!.textContent?.includes('pages.meteringPoints.planes.empty') === true, 'the empty state')
        await act(async () => { buttonWith(dialog()!, 'pages.meteringPoints.planes.add')!.click() })
        const inputs = Array.from(dialog()!.querySelectorAll<HTMLInputElement>('input'))
        await act(async () => { setInputValue(inputs[1], '8'); setInputValue(inputs[2], '120') })
        // The form does not use the browser's own check (its tooltip is in the browser's language): the handler holds on its own.
        await act(async () => { dialog()!.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
        expect(zev.createPvPlane).not.toHaveBeenCalled()
        expect(dialog()!.textContent).toContain('pages.meteringPoints.planes.errors.tilt')
        expect(dialog()!.textContent).not.toContain('pages.meteringPoints.planes.errors.kwp')
    })

    it('mentions the building location only while it is missing, with the way to set it', async () => {
        zev.fetchPvPlanes.mockResolvedValue([plane()])
        const onEditBuilding = vi.fn()
        const located = { id: 'b-1', latitude: '47.376910', longitude: '8.541690' } as Building
        const missing = { id: 'b-1', latitude: null, longitude: null } as Building

        await renderWithProviders(createElement(PvPlanesDialog, { point, canWrite: true, building: located, onEditBuilding, onClose: vi.fn() }), cleanups)
        await waitForCondition(() => dialog()!.textContent?.includes('South') === true, 'the planes')
        expect(dialog()!.textContent).not.toContain('pages.meteringPoints.planes.locationHint')
        cleanups.splice(0).forEach((cleanup) => cleanup())

        await renderWithProviders(createElement(PvPlanesDialog, { point, canWrite: true, building: missing, onEditBuilding, onClose: vi.fn() }), cleanups)
        await waitForCondition(() => dialog()!.textContent?.includes('South') === true, 'the planes')
        expect(dialog()!.textContent).toContain('pages.meteringPoints.planes.locationHint')
        await act(async () => { buttonWith(dialog()!, 'pages.meteringPoints.planes.editBuilding')!.click() })
        expect(onEditBuilding).toHaveBeenCalledWith(missing)
        cleanups.splice(0).forEach((cleanup) => cleanup())

        // Someone who cannot edit the building is told, without a button that would not work.
        await renderWithProviders(createElement(PvPlanesDialog, { point, canWrite: false, building: missing, onEditBuilding, onClose: vi.fn() }), cleanups)
        await waitForCondition(() => dialog()!.textContent?.includes('South') === true, 'the planes')
        expect(dialog()!.textContent).toContain('pages.meteringPoints.planes.locationHint')
        expect(buttonWith(dialog()!, 'pages.meteringPoints.planes.editBuilding')).toBeUndefined()
    })

    it('is read-only for someone who cannot write', async () => {
        zev.fetchPvPlanes.mockResolvedValue([plane()])
        await renderWithProviders(createElement(PvPlanesDialog, { point, canWrite: false, onClose: vi.fn() }), cleanups)
        await waitForCondition(() => dialog()!.textContent?.includes('South') === true, 'the planes')
        expect(buttonWith(dialog()!, 'pages.meteringPoints.planes.add')).toBeUndefined()
        expect(buttonWith(dialog()!, 'common.edit')).toBeUndefined()
        expect(buttonWith(dialog()!, 'common.delete')).toBeUndefined()
    })
})
