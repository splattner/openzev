import { createElement } from 'react'
import { act } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DynamicSourceSummary } from '../src/features/tariffs/DynamicSourceSummary'
import { renderWithProviders } from './helpers/render'
import type { AppSettings, DynamicTariffSource } from '../src/types/api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/appSettings', () => ({ formatDateTime: (value: string) => value }))

const source: DynamicTariffSource = {
    id: 'source-1', label: 'Shared source', url: 'https://prices.example.test',
    api_version: 'v1_0_5', tariff_type: 'grid', tariff_name: 'Standard', enabled: true,
    last_fetch_status: 'ok', last_fetch_at: null, last_success_at: null, last_fetch_error: '',
    covers_from: null, covers_to: null, point_count: 0, linked_tariff_count: 2, linked_zev_count: 1,
    supports_backfill: true, empty_on_not_found: false, aggregated_tariff_types: [], created_at: '', updated_at: '',
}

function render(overrides: Partial<DynamicTariffSource> = {}, canOperate = true) {
    return renderToStaticMarkup(createElement(MemoryRouter, null,
        createElement(DynamicSourceSummary, { source: { ...source, ...overrides }, settings: {} as AppSettings, canOperate })))
}

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

// The source's address and coverage sit in a disclosure, mounted when opened.
async function renderDetails(overrides: Partial<DynamicTariffSource> = {}) {
    const { container } = await renderWithProviders(
        createElement(DynamicSourceSummary, { source: { ...source, ...overrides }, settings: {} as AppSettings, canOperate: true }), cleanups)
    await act(async () => { container.querySelector('summary')!.click() })
    return container.innerHTML
}

describe('DynamicSourceSummary', () => {
    it('keeps the address and coverage behind the source details until they are opened', () => {
        const html = render({ point_count: 12, covers_from: '2026-09-01', covers_to: '2026-10-01' })
        expect(html).toContain('pages.dynamicSources.sourceDetails')
        expect(html).not.toContain('prices.example.test')
        expect(html).not.toContain('pages.dynamicSources.history.coverage')
    })

    it('shows no stored coverage without warning about gaps in an empty source', async () => {
        const html = await renderDetails()
        expect(html).toContain('pages.dynamicSources.noCoverage')
        expect(html).not.toContain('pages.dynamicSources.coverageHint')
        expect(html).not.toContain('pages.dynamicSources.history.coverage')
    })

    it('omits the last-success label until a successful fetch exists', () => {
        expect(render()).not.toContain('pages.dynamicSources.lastSuccess')
        expect(render({ last_success_at: '2026-10-01T12:00:00Z' })).toContain('pages.dynamicSources.lastSuccess')
    })

    it('shows stored coverage and the gap hint when points exist', async () => {
        const html = await renderDetails({ point_count: 12, covers_from: '2026-09-01', covers_to: '2026-10-01' })
        expect(html).toContain('pages.dynamicSources.history.coverage')
        expect(html).toContain('pages.dynamicSources.coverageHint')
        expect(html).not.toContain('pages.dynamicSources.noCoverage')
    })

    it('limits the maintenance link to users with operation permission', () => {
        expect(render()).toContain('/admin/dynamic-sources?source=source-1')
        expect(render({}, false)).not.toContain('pages.dynamicSources.manageSource')
    })
})
