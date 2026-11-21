import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RawMeteringTable } from '../src/components/RawMeteringTable'
import { queryKeys } from '../src/lib/api/queryKeys'

const calls = vi.hoisted(() => ({ assignments: [] as string[] }))

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en' } }),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
}))

vi.mock('../src/lib/api/metering', () => ({
    // A day without consumption, during an assignment: the holder-dependent flag case.
    fetchRawMeteringData: () => Promise.resolve([{ date: '2026-01-02', in_kwh: 0, out_kwh: 0, readings_count: 24 }]),
    fetchRawMeteringDay: () => Promise.resolve([]),
}))

vi.mock('../src/lib/api/zev', () => ({
    fetchMeteringPointAssignments: (meteringPoint: string) => {
        calls.assignments.push(meteringPoint)
        return Promise.resolve([{ id: 'a1', metering_point: 'mp1', participant: 'p1', valid_from: '2026-01-01', valid_to: null }])
    },
}))

const unmounts: Array<() => void> = []

async function renderTable(canReadAssignments: boolean, meterType?: 'consumption' | 'production') {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    // Assignments cached earlier, e.g. while the account still had management access.
    client.setQueryData(queryKeys.metering.pointAssignments('mp1'), [
        { id: 'a1', metering_point: 'mp1', participant: 'p1', valid_from: '2026-01-01', valid_to: null },
    ])
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    await act(async () => {
        root.render(createElement(MantineProvider, null, createElement(QueryClientProvider, { client },
            createElement(RawMeteringTable, { meteringPointId: 'mp1', dateFrom: '2026-01-01', dateTo: '2026-01-31', hasOut: false, meterType, canReadAssignments, canReadHeld: false }))))
    })
    await vi.waitFor(() => expect(container.textContent).toContain('2026-01-02'))
    unmounts.push(() => { act(() => root.unmount()); container.remove() })
    return container
}

afterEach(() => {
    unmounts.splice(0).forEach((unmount) => unmount())
    calls.assignments = []
})

describe('raw metering table assignment access', () => {
    it('neither requests nor uses cached assignments without access', async () => {
        const container = await renderTable(false)
        expect(calls.assignments).toEqual([])
        expect(container.textContent).not.toContain('pages.meteringData.rawTable.zeroConsumptionFlag')
    })

    it('flags a zero-consumption day with a holder for management readers', async () => {
        const container = await renderTable(true)
        expect(container.textContent).toContain('pages.meteringData.rawTable.zeroConsumptionFlag')
    })

    it('does not flag zero consumption on a production meter', async () => {
        const container = await renderTable(true, 'production')
        expect(container.textContent).not.toContain('pages.meteringData.rawTable.zeroConsumptionFlag')
    })
})
