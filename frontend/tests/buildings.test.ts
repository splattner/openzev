import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { Building, MeteringPointInput } from '../src/types/api'

// Buildings (#890): the metering-point form shows a building select only for a
// ZEV with several, and a participant can copy a building's address.

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {}, isLoading: false }),
    toDayJsDateFormat: () => 'YYYY-MM-DD',
}))
vi.mock('../src/lib/api/zev', () => ({
    fetchParties: vi.fn(async () => []),
    fetchBuildings: vi.fn(),
}))

import { fetchBuildings } from '../src/lib/api/zev'
import { MeteringPointFormModal } from '../src/features/meteringPoints/MeteringPointFormModal'
import { ParticipantFormModal } from '../src/features/participants/ParticipantFormModal'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const building = (id: string, name: string, over: Partial<Building> = {}): Building => ({
    id, zev: 'zev-1', name, address_line1: '', address_line2: '', postal_code: '', city: '', egid: null, notes: '',
    metering_point_count: 0, created_at: '', updated_at: '', ...over,
})

function Harness({ buildings }: { buildings: Building[] }) {
    const [form, setForm] = useState<MeteringPointInput>({
        zev: 'zev-1', meter_id: 'M-1', meter_type: 'consumption', is_active: true, location_description: '',
    })
    return createElement(MeteringPointFormModal, {
        isOpen: true,
        title: 'title',
        submitLabel: 'submit',
        form,
        isPending: false,
        onClose: () => undefined,
        onSubmit: (event) => event.preventDefault(),
        setForm,
        buildings,
    })
}

describe('buildings in forms', () => {
    let container: HTMLDivElement
    let root: ReturnType<typeof createRoot>

    beforeEach(() => {
        Object.defineProperty(window, 'matchMedia', {
            writable: true,
            configurable: true,
            value: (query: string) => ({
                matches: false, media: query, onchange: null,
                addListener: () => undefined, removeListener: () => undefined,
                addEventListener: () => undefined, removeEventListener: () => undefined,
                dispatchEvent: () => false,
            }),
        })
        container = document.createElement('div')
        document.body.appendChild(container)
        root = createRoot(container)
    })

    afterEach(() => {
        act(() => root.unmount())
        container.remove()
        vi.clearAllMocks()
    })

    function render(node: ReturnType<typeof createElement>) {
        act(() => {
            root.render(createElement(QueryClientProvider, { client: new QueryClient() }, createElement(MantineProvider, null, node)))
        })
    }

    const hasBuildingSelect = () =>
        Array.from(document.querySelectorAll('label span')).some((span) => span.textContent === 'Building')

    it('hides the building select for a ZEV with one building', () => {
        render(createElement(Harness, { buildings: [building('b1', 'Haus A')] }))
        expect(document.querySelector('form')).toBeTruthy()
        expect(hasBuildingSelect()).toBe(false)
    })

    it('shows the building select, listing every building, for a ZEV with several', () => {
        render(createElement(Harness, { buildings: [building('b1', 'Haus A'), building('b2', 'Haus B')] }))
        expect(hasBuildingSelect()).toBe(true)
        const options = Array.from(document.querySelectorAll('option')).map((option) => option.textContent)
        expect(options).toEqual(expect.arrayContaining(['Haus A', 'Haus B']))
    })

    it('copies a building\'s address into the new participant form', async () => {
        vi.mocked(fetchBuildings).mockResolvedValue([
            building('b1', 'Haus A', { address_line1: 'Weg 1', address_line2: 'Hinterhaus', postal_code: '3000', city: 'Bern' }),
        ])
        render(createElement(ParticipantFormModal, {
            isOpen: true, title: 'title', onClose: () => undefined, onSubmit: () => undefined,
            selectedZevId: 'zev-1', isPending: false,
        }))
        const copy = async () => {
            for (let i = 0; i < 20; i += 1) {
                const button = Array.from(document.querySelectorAll('button')).find((candidate) =>
                    candidate.textContent?.includes('Copy address from Haus A'),
                )
                if (button) return button
                await act(async () => { await new Promise((resolve) => setTimeout(resolve, 25)) })
            }
            return null
        }
        const button = await copy()
        expect(button, 'copy button not rendered').toBeTruthy()
        await act(async () => { button!.click() })
        const value = (name: string) => document.querySelector<HTMLInputElement>(`input[name="${name}"]`)?.value
        expect([value('address_line1'), value('address_line2'), value('postal_code'), value('city')]).toEqual([
            'Weg 1', 'Hinterhaus', '3000', 'Bern',
        ])
    })
})
