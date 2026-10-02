import { act, createElement, type ReactElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { ParticipantToolbar } from '../src/features/participants/ParticipantToolbar'
import { TariffToolbar } from '../src/features/tariffs/TariffToolbar'
import { TariffEmptyState } from '../src/features/tariffs/TariffEmptyState'
import { ImportHistoryTable } from '../src/features/imports/ImportHistoryTable'

// A viewer sees a ZEV's management pages but no write controls (#761,
// SPEC-2026-10-zev-access-grants §9.5). The backend refuses the writes anyway.

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function render(element: ReactElement) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(createElement(MantineProvider, null, createElement(MemoryRouter, null, element))))
    return container
}

const has = (container: Element, label: string) => container.textContent?.includes(label) ?? false

describe('viewer read-only controls', () => {
    it('participants: no "New participant"', async () => {
        const props = {
            totalCount: 1, ownerCount: 0, warningCount: 0, noMeteringCount: 0, searchTerm: '',
            readinessFilter: 'all' as const, onSearchTermChange: vi.fn(), onReadinessFilterChange: vi.fn(),
            onOpenCreateModal: vi.fn(),
        }
        expect(has(await render(createElement(ParticipantToolbar, props)), 'pages.participants.newParticipant')).toBe(true)
        expect(has(await render(createElement(ParticipantToolbar, { ...props, readOnly: true })), 'pages.participants.newParticipant')).toBe(false)
    })

    it('tariffs: no "New tariff" or import, but the overview PDF stays', async () => {
        const props = {
            tariffCount: 1, energyTariffCount: 1, tariffsWithPeriodsCount: 0, periodCount: 0,
            validityFilter: 'all' as const, onValidityFilterChange: vi.fn(), onOpenCreateTariffModal: vi.fn(),
            onDownloadOverview: vi.fn(),
        }
        const viewer = await render(createElement(TariffToolbar, { ...props, readOnly: true }))
        expect(has(viewer, 'pages.tariffs.newTariff')).toBe(false)
        expect(has(viewer, 'pages.tariffs.import.action')).toBe(false)
        expect(has(viewer, 'pages.tariffs.overviewPdf.action')).toBe(true)
        expect(has(await render(createElement(TariffToolbar, props)), 'pages.tariffs.newTariff')).toBe(true)
    })

    it('tariffs empty state: no create action', async () => {
        expect(has(await render(createElement(TariffEmptyState, { onOpenCreateTariffModal: vi.fn(), readOnly: true })), 'pages.tariffs.newTariff')).toBe(false)
    })

    it('imports: an empty history offers no new import', async () => {
        const props = { rows: [], columns: [], getRowId: () => '', filters: [], onFiltersChange: vi.fn() }
        expect(has(await render(createElement(ImportHistoryTable, props)), 'pages.imports.emptyState.createAction')).toBe(false)
        expect(has(await render(createElement(ImportHistoryTable, { ...props, onNewImport: vi.fn() })), 'pages.imports.emptyState.createAction')).toBe(true)
    })
})
