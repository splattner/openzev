import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createInstance } from 'i18next'
import { I18nextProvider, initReactI18next } from 'react-i18next'
import { en } from '../src/i18n/locales/en'
import { RawMeteringTable } from '../src/components/RawMeteringTable'
import { queryKeys } from '../src/lib/api/queryKeys'

const api = vi.hoisted(() => ({
    fetchRawMeteringData: vi.fn(),
    fetchRawMeteringDay: vi.fn(),
    fetchHeldMeteringReadings: vi.fn(),
}))

const i18n = createInstance()
beforeAll(async () => {
    await i18n.use(initReactI18next).init({
        lng: 'en', resources: { en: { translation: en } }, interpolation: { escapeValue: false },
    })
})

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: { date_time_format: 'yyyy-MM-dd HH:mm' } }),
    formatShortDate: (date: string) => date,
    formatDateTime: (value: string) => value,
}))

vi.mock('../src/lib/api/metering', () => ({
    fetchRawMeteringData: api.fetchRawMeteringData,
    fetchRawMeteringDay: api.fetchRawMeteringDay,
    fetchHeldMeteringReadings: api.fetchHeldMeteringReadings,
}))

vi.mock('../src/lib/api/zev', () => ({
    fetchMeteringPointAssignments: () => Promise.resolve([]),
}))

const unmounts: Array<() => void> = []
const heldKey = queryKeys.metering.heldReadings('mp1', '2026-01-01', '2026-12-31', '', 1)

async function renderTable(day: string, overrides: { canReadHeld?: boolean; client?: QueryClient } = {}) {
    const client = overrides.client ?? new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(
                MantineProvider,
                null,
                createElement(
                    QueryClientProvider,
                    { client },
                    createElement(I18nextProvider, { i18n }, createElement(RawMeteringTable, {
                        meteringPointId: 'mp1',
                        dateFrom: '2026-01-01',
                        dateTo: '2026-12-31',
                        hasOut: false,
                        canReadAssignments: false,
                        canReadHeld: overrides.canReadHeld ?? true,
                    })),
                ),
            ),
        )
    })
    await vi.waitFor(() => expect(container.textContent).toContain(day))
    unmounts.push(() => {
        act(() => root.unmount())
        container.remove()
    })
    return container
}

/** Expand the day row. */
async function openDay(container: HTMLElement) {
    const row = container.querySelector<HTMLTableRowElement>('tr.raw-metering-day')
    await act(async () => {
        row?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
}

function reading(overrides: Record<string, unknown>) {
    return {
        direction: 'in',
        energy_kwh: 1,
        resolution: '15min',
        import_source: 'sdatch',
        condition: '',
        ...overrides,
    }
}

function heldReading(overrides: Record<string, unknown> = {}) {
    return {
        id: 'q1', metering_point: 'mp1', meter_id: 'M-1', timestamp: '2026-01-02T00:00:00Z',
        direction: 'in', energy_kwh: '9.0000', resolution: '15min', condition: '21',
        business_reason: 'E88', import_source: 'sdatch', import_batch: 'b1',
        source_document_id: 'DOC', source_delivery_id: 'DEL', source_creation: null,
        source_product: '', source_unit: 'KWH', source_meter_id: 'M-1',
        created_at: '2026-01-03T00:00:00Z',
        accepted_energy_kwh: null,
        ...overrides,
    }
}

afterEach(() => {
    unmounts.splice(0).forEach((unmount) => unmount())
    api.fetchRawMeteringData.mockReset()
    api.fetchRawMeteringDay.mockReset()
    api.fetchHeldMeteringReadings.mockReset()
})

describe('raw metering reading quality', () => {
    it('marks an estimated interval and names its quality in the detail', async () => {
        api.fetchRawMeteringData.mockResolvedValue([
            { date: '2026-01-02', in_kwh: 3, out_kwh: 0, readings_count: 2 },
        ])
        api.fetchRawMeteringDay.mockResolvedValue([
            reading({ timestamp: '2026-01-02T00:00:00Z' }),
            reading({ timestamp: '2026-01-02T00:15:00Z', energy_kwh: 2, condition: '56' }),
            reading({ timestamp: '2026-01-02T00:30:00Z', energy_kwh: 0, condition: '99' }),
        ])
        api.fetchHeldMeteringReadings.mockResolvedValue({ count: 0, page_size: 50, next: null, previous: null, results: [] })
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        const container = await renderTable('2026-01-02', { client })
        await act(async () => {
            await vi.waitFor(() => expect(client.getQueryState(heldKey)?.status).toBe('success'))
        })
        expect(container.querySelector('.held-readings')).toBeNull()
        await openDay(container)

        await vi.waitFor(() =>
            expect(container.textContent).toContain('≈ estimated value'),
        )
        // Exactly the estimated interval is marked, not the whole day.
        expect(container.querySelectorAll('.raw-metering-quality-marker')).toHaveLength(1)

        // The estimated cell opens on that interval's own quality and code.
        const cells = Array.from(container.querySelectorAll<HTMLButtonElement>('.raw-metering-cell-button'))
        expect(cells.some((cell) => cell.getAttribute('aria-label')?.includes('Condition 99'))).toBe(true)
        const estimatedCell = cells.find((cell) =>
            cell.getAttribute('aria-label')?.includes('Estimated'),
        )
        expect(estimatedCell).toBeDefined()
        await act(async () => {
            estimatedCell?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        const detail = container.querySelector('.raw-metering-cell-detail')
        expect(detail?.textContent).toContain('Estimated')
        expect(detail?.textContent).toContain('(56)')
        const unknownCell = cells.find((cell) => cell.getAttribute('aria-label')?.includes('Condition 99'))
        await act(async () => unknownCell?.click())
        expect(container.querySelector('.raw-metering-cell-detail')?.textContent).toContain('Condition 99')
        expect(container.querySelector('.raw-metering-cell-detail')?.textContent).not.toContain('99 (99)')
    })

    it('exposes both intervals when one cell holds two readings of different quality', async () => {
        // The autumn DST day: 00:00Z and 01:00Z are both 02:00 Swiss local time,
        // so they share one grid cell.
        api.fetchRawMeteringData.mockResolvedValue([
            { date: '2026-10-25', in_kwh: 3, out_kwh: 0, readings_count: 2 },
        ])
        api.fetchRawMeteringDay.mockResolvedValue([
            reading({ timestamp: '2026-10-25T00:00:00Z' }),
            reading({ timestamp: '2026-10-25T01:00:00Z', energy_kwh: 2, condition: '56' }),
        ])
        api.fetchHeldMeteringReadings.mockResolvedValue({ count: 0, page_size: 50, next: null, previous: null, results: [] })
        const container = await renderTable('2026-10-25')
        await openDay(container)

        await vi.waitFor(() =>
            expect(container.textContent).toContain('≈ estimated value'),
        )
        // The repeated hour is marked as aggregated, not silently summed.
        expect(container.textContent).toContain('·2')

        const cell = container.querySelector<HTMLButtonElement>('.raw-metering-cell-button[aria-expanded="false"]')
        await act(async () => {
            cell?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        const detail = container.querySelector('.raw-metering-cell-detail')
        expect(detail?.querySelectorAll('li')).toHaveLength(2)
        expect(detail?.textContent).toContain('Unflagged')
        expect(detail?.textContent).toContain('Estimated')
        expect(detail?.textContent).toContain('2026-10-25 02:00 GMT+02:00')
        expect(detail?.textContent).toContain('2026-10-25 02:00 GMT+01:00')
    })

    it.each([false, true])('keeps failed held reads retryable with cached empty data: %s', async (cachedEmpty) => {
        api.fetchRawMeteringData.mockResolvedValue([
            { date: '2026-01-02', in_kwh: 1, out_kwh: 0, readings_count: 1 },
        ])
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        if (cachedEmpty) client.setQueryData(heldKey, { count: 0, page_size: 50, results: [] })
        api.fetchHeldMeteringReadings.mockRejectedValue(new Error('Unavailable'))
        const container = await renderTable('2026-01-02', { client })
        await vi.waitFor(() => expect(client.getQueryState(heldKey)?.status).toBe('error'))
        const toggle = Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Show held observations')
        expect(toggle).toBeDefined()
        await act(async () => toggle?.click())
        expect(container.textContent).toContain('Failed to load held observations')
        api.fetchHeldMeteringReadings.mockResolvedValue({ count: 1, page_size: 50, results: [heldReading()] })
        await act(async () => Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Retry')?.click())
        await vi.waitFor(() => expect(container.textContent).toContain('9.0000'))
        await act(async () => client.setQueryData(heldKey, { count: 0, page_size: 50, results: [] }))
        await vi.waitFor(() => expect(container.textContent).toContain('No held observations match this selection.'))
    })

    it('does not offer the held section on a participant surface', async () => {
        api.fetchRawMeteringData.mockResolvedValue([
            { date: '2026-01-02', in_kwh: 1, out_kwh: 0, readings_count: 1 },
        ])
        api.fetchRawMeteringDay.mockResolvedValue([
            reading({ timestamp: '2026-01-02T00:00:00Z' }),
        ])
        const container = await renderTable('2026-01-02', { canReadHeld: false })

        expect(container.textContent).not.toContain('Show held observations')
        expect(api.fetchHeldMeteringReadings).not.toHaveBeenCalled()
    })

    it('shows held observations and keeps zero apart from a missing accepted reading', async () => {
        api.fetchRawMeteringData.mockResolvedValue([
            { date: '2026-01-02', in_kwh: 0, out_kwh: 0, readings_count: 1 },
        ])
        api.fetchRawMeteringDay.mockResolvedValue([
            reading({ timestamp: '2026-01-02T00:00:00Z', energy_kwh: 0 }),
        ])
        api.fetchHeldMeteringReadings.mockResolvedValue({
            count: 2,
            page_size: 50,
            next: null,
            previous: null,
            results: [
                heldReading({ accepted_energy_kwh: '0.0000' }),
                heldReading({ id: 'q2', direction: 'out', business_reason: 'C38', accepted_energy_kwh: null }),
            ],
        })
        const container = await renderTable('2026-01-02')

        const toggle = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
            (button) => button.textContent === 'Show held observations',
        )
        expect(toggle).toBeDefined()
        await act(async () => {
            toggle?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })

        await vi.waitFor(() =>
            expect(container.textContent).toContain('A held value does not replace'),
        )
        // Held values never join the accepted total, and an accepted zero is
        // shown as such rather than as "no accepted reading".
        expect(container.textContent).toContain('0.0000 kWh')
        expect(container.textContent).toContain('No accepted reading')
        expect(container.textContent).toContain('Production / feed-in (out)')
        expect(container.textContent).toContain('Billing energy (E88)')
        expect(container.textContent).toContain('Information-only delivery (C38)')
    })

    it('uses the server page size for a short final page', async () => {
        api.fetchRawMeteringData.mockResolvedValue([
            { date: '2026-01-02', in_kwh: 0, out_kwh: 0, readings_count: 0 },
        ])
        api.fetchHeldMeteringReadings.mockImplementation(({ page }) => Promise.resolve({
            count: 3, page_size: 2,
            next: page === 1 ? '?page=2' : null, previous: page === 2 ? '?page=1' : null,
            results: page === 1 ? [heldReading(), heldReading({ id: 'q2' })] : [heldReading({ id: 'q3' })],
        }))
        const container = await renderTable('2026-01-02')
        await act(async () => {
            Array.from(container.querySelectorAll('button')).find(button => button.textContent === 'Show held observations')?.click()
        })
        await vi.waitFor(() => expect(container.textContent).toContain('1–2 of 3'))
        await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Next page"]')?.click())
        await vi.waitFor(() => expect(container.textContent).toContain('3–3 of 3'))
        expect(container.querySelector('.held-readings .data-table-footer')?.textContent).toContain('2 / 2')
        expect(container.querySelector<HTMLButtonElement>('button[aria-label="Next page"]')?.disabled).toBe(true)
    })

    it.each([500, 404])('recovers from a failed or removed later page (%s)', async (status) => {
        api.fetchRawMeteringData.mockResolvedValue([
            { date: '2026-01-02', in_kwh: 0, out_kwh: 0, readings_count: 0 },
        ])
        api.fetchHeldMeteringReadings.mockImplementation(({ page }) => page === 2
            ? Promise.reject({ response: { status } })
            : Promise.resolve({ count: 51, page_size: 50, results: [heldReading()] }))
        const container = await renderTable('2026-01-02')
        const click = async (label: string) => {
            const button = Array.from(container.querySelectorAll('button')).find(
                button => button.getAttribute('aria-label') === label || button.textContent === label,
            )
            expect(button, label).toBeDefined()
            await act(async () => button?.click())
        }
        await click('Show held observations')
        await vi.waitFor(() => expect(container.textContent).toContain('9.0000'))
        await click('Next page')
        await vi.waitFor(() => expect(container.textContent).toContain('Failed to load held observations'))
        await click('Retry')
        await vi.waitFor(() => expect(api.fetchHeldMeteringReadings).toHaveBeenCalledTimes(3))
        api.fetchHeldMeteringReadings.mockResolvedValue({ count: 1, page_size: 50, results: [heldReading()] })
        await click('Back to first page')
        await vi.waitFor(() => expect(container.textContent).toContain('9.0000'))
        expect(api.fetchHeldMeteringReadings).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1 }))
    })

})
