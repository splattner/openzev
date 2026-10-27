import { createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TariffOverview } from '../src/features/tariffs/TariffOverview'
import { tariffOverview } from '../src/features/tariffs/validity'
import { TariffVersionForm } from '../src/features/tariffs/TariffVersionForm'
import { renderWithProviders, setInputValue } from './helpers/render'
import { act } from 'react'
import type { TariffSeries, TariffVersion } from '../src/types/api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/api/tariffs', () => ({ fetchDynamicTariffSources: vi.fn().mockResolvedValue([]) }))

// The overview is Current, Upcoming and a folded History, with no totals (SPEC-2026-10-tariff-split-view §4).

const settings = { date_format_short: 'dd.MM.yyyy', date_format_long: 'd MMMM yyyy', date_time_format: 'dd.MM.yyyy HH:mm', updated_at: '' }
const TODAY = new Date().toISOString().slice(0, 10)
const version = (id: string, valid_from: string, valid_to: string | null): TariffVersion => ({
    id, zev: 'z', name: 'Grid', category: 'grid_fees', billing_mode: 'monthly_fee', energy_type: null,
    valid_from, valid_to, fixed_price_chf: '10.00', split_key: 'equal', notes: '', periods: [],
}) as unknown as TariffVersion
const past = version('past', '2000-01-01', '2000-12-31')
const current = version('current', '2001-01-01', null)
const next = version('next', '2999-01-01', null)
const series = { zev: 'z', name: 'Grid', category: 'grid_fees', billing_mode: 'monthly_fee', energy_type: null,
    version_count: 3, active_version_id: 'current', gaps: [], versions: [next, current, past] } as unknown as TariffSeries

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function list(selected: { seriesKey: string, versionId: string } | null = null, onlyPast = false) {
    const groups = tariffOverview([onlyPast ? ({ ...series, versions: [past] } as TariffSeries) : series], TODAY)
    const { container } = await renderWithProviders(createElement(TariffOverview, { groups, settings, selected, onOpenDetail: vi.fn() }), cleanups)
    return container
}

describe('TariffOverview', () => {
    it('groups by what is in force, what is coming and, folded, what has ended', async () => {
        const upcomingOnly = { ...series, name: 'Soon', versions: [next] } as unknown as TariffSeries
        const pastOnly = { ...series, name: 'Old', versions: [past] } as unknown as TariffSeries
        const groups = tariffOverview([series, upcomingOnly, pastOnly], TODAY)
        const { container } = await renderWithProviders(createElement(TariffOverview, { groups, settings, selected: null, onOpenDetail: vi.fn() }), cleanups)
        expect([...container.querySelectorAll('h2')].map((h) => h.textContent)).toEqual([
            'pages.tariffs.overview.current', 'pages.tariffs.overview.upcoming', 'pages.tariffs.overview.history',
        ])
        expect(container.querySelector<HTMLDetailsElement>('details.tariff-overview-history')!.open).toBe(false)
    })

    it('gives a tariff one row, and says in it what the next version changes', async () => {
        const container = await list()
        const rows = [...container.querySelectorAll('tbody tr')].map((row) => row.getAttribute('data-row-key'))
        expect(rows).toEqual(['z:Grid:current'])
        expect(container.querySelector('.tariff-table-valid .badge')).toBeNull()
        const change = container.querySelector<HTMLButtonElement>('.tariff-next-change')!
        expect(change.textContent).toBe('pages.tariffs.overview.nextPrices')
    })

    it('opens the next version from the row, and highlights the row for it', async () => {
        const onOpenDetail = vi.fn()
        const groups = tariffOverview([series], TODAY)
        const { container } = await renderWithProviders(createElement(TariffOverview, {
            groups, settings, selected: { seriesKey: 'z:Grid', versionId: 'next' }, onOpenDetail,
        }), cleanups)
        expect(container.querySelector('tr.is-selected')?.getAttribute('data-row-key')).toBe('z:Grid:current')
        await act(async () => { container.querySelector<HTMLButtonElement>('.tariff-next-change')!.click() })
        expect(onOpenDetail).toHaveBeenCalledWith(series, 'next')
        expect(onOpenDetail).toHaveBeenCalledTimes(1)
    })

    it('has no totals', async () => {
        const container = await list()
        expect(container.querySelector('.badge-neutral')).toBeNull()
        expect(container.textContent).not.toMatch(/\b3\b/)
    })

    it('unfolds History when the selected version is a past one of a tariff that has ended', async () => {
        const container = await list({ seriesKey: 'z:Grid', versionId: 'past' }, true)
        expect(container.querySelector<HTMLDetailsElement>('details.tariff-overview-history')!.open).toBe(true)
    })

    it('says so when nothing is in force, and keeps a past-only tariff reachable', async () => {
        const container = await list(null, true)
        expect(container.querySelector('p.muted')?.textContent).toBe('pages.tariffs.overview.nothingCurrent')
        expect(container.querySelectorAll('details.tariff-overview-history tbody tr')).toHaveLength(1)
        expect(container.querySelector('.tariff-next-change')).toBeNull()
    })
})

describe('TariffVersionForm', () => {
    it('reports unsaved input only once something differs from what it was seeded with', async () => {
        const onDirtyChange = vi.fn()
        const { container } = await renderWithProviders(createElement(TariffVersionForm, {
            dialog: { kind: 'rename', series, source: current }, settings, isPending: false, onCancel: vi.fn(), onDirtyChange,
            onSubmitNewVersion: vi.fn(), onSubmitDuplicate: vi.fn(), onSubmitRename: vi.fn(),
        }), cleanups)
        expect(onDirtyChange).toHaveBeenLastCalledWith(false)
        const name = container.querySelector<HTMLInputElement>('input')!
        await act(async () => setInputValue(name, 'Grid 2'))
        expect(onDirtyChange).toHaveBeenLastCalledWith(true)
        await act(async () => setInputValue(name, 'Grid'))
        expect(onDirtyChange).toHaveBeenLastCalledWith(false)
    })

    it('puts the cursor in the first field and locks the fields while saving', async () => {
        const { container } = await renderWithProviders(createElement(TariffVersionForm, {
            dialog: { kind: 'rename', series, source: current }, settings, isPending: true, onCancel: vi.fn(), onDirtyChange: vi.fn(),
            onSubmitNewVersion: vi.fn(), onSubmitDuplicate: vi.fn(), onSubmitRename: vi.fn(),
        }), cleanups)
        expect(container.querySelector('form')?.getAttribute('aria-busy')).toBe('true')
        expect(container.querySelector('fieldset')?.disabled).toBe(true)
        expect(container.querySelector('button[type="submit"]')?.textContent).toContain('common.saving')
    })
})
