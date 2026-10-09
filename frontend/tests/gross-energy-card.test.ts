import { createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GrossEnergyCallToAction, GrossEnergyCard } from '../src/components/dashboard/GrossEnergyCard'
import { NetMeteredRate } from '../src/components/dashboard/NetMeteredRate'
import type { GrossEnergy } from '../src/types/api'
import { renderWithProviders } from './helpers/render'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options?.provider ? `${key}|${options.provider}` : key) }),
}))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: actual.DEFAULT_APP_SETTINGS, isLoading: false }) }
})

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

const gross = (overrides: Partial<GrossEnergy> = {}): GrossEnergy => ({
    source_provider: 'solar_manager',
    covered_from: '2026-07-01T00:00:00Z',
    covered_to: '2026-07-04T00:00:00Z',
    coverage_pct: 100,
    production_kwh: 345.6,
    consumption_kwh: 115.2,
    import_kwh: 28.8,
    export_kwh: 259.2,
    self_consumption_kwh: 86.4,
    self_consumption_rate: 25,
    self_sufficiency_rate: 75,
    rates_withheld_reason: null,
    ...overrides,
})

const card = (g: GrossEnergy, whose: 'own' | 'participant' = 'own', name?: string) =>
    createElement(GrossEnergyCard, {
        gross: g,
        whose,
        participantName: name,
        formatBucketLabel: (value: string) => value,
        formatBucketTooltipLabel: (label: unknown) => String(label),
    })

describe('GrossEnergyCard', () => {
    it('shows both rates and says the figures come from the participant\'s own system', async () => {
        const { container } = await renderWithProviders(card(gross()), cleanups)

        const text = container.textContent ?? ''
        expect(text).toContain('75')
        expect(text).toContain('25')
        expect(text).toContain('supplementary.gross.reportedOwn|supplementary.provider.solar_manager')
        expect(text).toContain('supplementary.gross.basedOn')
        expect(text).not.toContain('supplementary.withheld')
    })

    it('shows a dash and the reason instead of a low rate when coverage is too thin', async () => {
        const { container } = await renderWithProviders(
            card(gross({ rates_withheld_reason: 'low_coverage', self_sufficiency_rate: null, self_consumption_rate: null })),
            cleanups,
        )

        const values = Array.from(container.querySelectorAll('.stat-value')).map((node) => node.textContent)
        expect(values.slice(0, 2)).toEqual(['—', '—'])
        expect(container.textContent).toContain('supplementary.withheld.lowCoverage')
        // The energy itself is still reported.
        expect(container.textContent).toContain('345')
    })

    it('says there is no data when there is none', async () => {
        const { container } = await renderWithProviders(
            card(gross({ rates_withheld_reason: 'no_data', self_sufficiency_rate: null, self_consumption_rate: null, coverage_pct: 0 })),
            cleanups,
        )

        expect(container.textContent).toContain('supplementary.withheld.noData')
    })

    it('names the participant when an owner looks at someone else\'s figures', async () => {
        const { container } = await renderWithProviders(card(gross(), 'participant', 'Pia Muster'), cleanups)

        expect(container.querySelector('h3')?.textContent).toContain('Pia Muster')
        expect(container.textContent).toContain('supplementary.gross.reportedParticipant')
    })

    it('is a labelled region', async () => {
        const { container } = await renderWithProviders(card(gross()), cleanups)

        const section = container.querySelector('section')!
        expect(document.getElementById(section.getAttribute('aria-labelledby')!)).not.toBeNull()
    })
})

describe('GrossEnergyCallToAction', () => {
    it('links to the Energy data tab', async () => {
        const { container } = await renderWithProviders(createElement(GrossEnergyCallToAction), cleanups)

        expect(container.querySelector('a')?.getAttribute('href')).toBe('/account?tab=energy-data')
    })
})

describe('NetMeteredRate', () => {
    it('shows the rate with a marker saying where it comes from', async () => {
        const { container } = await renderWithProviders(createElement(NetMeteredRate, { gross: gross() }), cleanups)

        expect(container.textContent).toContain('75')
        expect(container.querySelector('[title="supplementary.rateHint"]')).not.toBeNull()
    })

    it('is a plain dash without a source', async () => {
        const { container } = await renderWithProviders(createElement(NetMeteredRate, { gross: null }), cleanups)

        expect(container.querySelector('span')?.textContent).toBe('—')
        expect(container.querySelector('span[title]')).toBeNull()
    })

    it('is a dash with the reason when the data is too thin', async () => {
        const { container } = await renderWithProviders(
            createElement(NetMeteredRate, { gross: gross({ rates_withheld_reason: 'low_coverage', self_sufficiency_rate: null }) }),
            cleanups,
        )

        expect(container.querySelector('span')?.textContent).toBe('—')
        expect(container.querySelector('[title="supplementary.withheld.lowCoverage"]')).not.toBeNull()
    })
})
