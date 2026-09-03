import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from '../src/lib/api/client'
import { applyVseTariffImport, previewVseTariffImport } from '../src/lib/api/tariffs'
import {
    defaultBillingModes,
    isSelectable,
    recommendedKeys,
    selectionFor,
    toggleKey,
    trimPrice,
} from '../src/features/tariffs/vseImportSelection'
import type { VseTariffCandidate } from '../src/types/api'

/**
 * The tariff import wizard writes into a ZEV's billing configuration, so the
 * two things worth pinning down outside manual QA are which rows it lets you
 * tick (and pre-ticks for you) and what it actually sends back to the server.
 */
function candidate(overrides: Partial<VseTariffCandidate> = {}): VseTariffCandidate {
    return {
        key: 'Netznutzung Basis (Arbeitspreis)@2027-01-01',
        name: 'Netznutzung Basis (Arbeitspreis)',
        category: 'grid_fees',
        billing_mode: 'energy',
        billing_mode_options: [],
        energy_type: 'grid',
        fixed_price_chf: null,
        valid_from: '2027-01-01',
        valid_to: '2027-12-31',
        notes: '',
        periods: [
            { period_type: 'flat', price_chf_per_kwh: '0.10600', time_from: null, time_to: null, weekdays: '' },
        ],
        source_tariff_name: 'Netznutzung Basis',
        source_tariff_type: 'grid',
        source_customer_type: 'Haushalte',
        source_voltage_level: 7,
        standard_basegroup: true,
        status: 'new',
        detail: 'Creates a new tariff.',
        warnings: [],
        recommended: true,
        effective_valid_to: '2027-12-31',
        ...overrides,
    }
}

describe('which candidates can be imported', () => {
    it('allows a new tariff and a new version of an existing one', () => {
        expect(isSelectable(candidate({ status: 'new' }))).toBe(true)
        expect(isSelectable(candidate({ status: 'new_version' }))).toBe(true)
    })

    it('refuses the statuses the backend would skip anyway', () => {
        // Ticking these would promise something the apply step will not do.
        expect(isSelectable(candidate({ status: 'duplicate' }))).toBe(false)
        expect(isSelectable(candidate({ status: 'conflict' }))).toBe(false)
        expect(isSelectable(candidate({ status: 'unsupported' }))).toBe(false)
    })
})

describe('what the wizard pre-selects', () => {
    it('ticks only the operator’s own standard product', () => {
        const keys = recommendedKeys([
            candidate({ key: 'standard', recommended: true }),
            candidate({ key: 'other-product', recommended: false }),
        ])

        expect([...keys]).toEqual(['standard'])
    })

    it('never ticks a recommended candidate that cannot be applied', () => {
        // A document imported once already: recommended, but re-importing it
        // would do nothing, so a ticked box would be a lie.
        const keys = recommendedKeys([candidate({ recommended: true, status: 'duplicate' })])

        expect(keys.size).toBe(0)
    })

    it('toggles a key on and back off', () => {
        const once = toggleKey(new Set<string>(), 'a')
        const twice = toggleKey(once, 'a')

        expect([...once]).toEqual(['a'])
        expect(twice.size).toBe(0)
    })
})

describe('the billing mode a fee is imported as', () => {
    const fee = () =>
        candidate({
            key: 'fee',
            name: 'Netznutzung Basis (Grundpreis)',
            billing_mode: 'shared_monthly_fee',
            billing_mode_options: ['shared_monthly_fee', 'monthly_fee', 'per_metering_point_monthly_fee'],
            fixed_price_chf: '7.00',
            periods: [],
        })

    it('starts every candidate on the mode the backend proposed', () => {
        expect(defaultBillingModes([fee(), candidate({ key: 'energy' })])).toEqual({
            fee: 'shared_monthly_fee',
            energy: 'energy',
        })
    })

    it('sends no override when the proposed mode was left alone', () => {
        // An untouched row must not carry a mode the server then has to
        // re-validate against a list it already chose from.
        expect(selectionFor(fee(), 'shared_monthly_fee')).toEqual({ key: 'fee' })
        expect(selectionFor(fee(), undefined)).toEqual({ key: 'fee' })
    })

    it('sends the picked mode when the user changed it', () => {
        expect(selectionFor(fee(), 'per_metering_point_monthly_fee')).toEqual({
            key: 'fee',
            billing_mode: 'per_metering_point_monthly_fee',
        })
    })
})

describe('price display', () => {
    it('drops the stored precision padding', () => {
        expect(trimPrice('0.10600')).toBe('0.106')
        expect(trimPrice('7.00')).toBe('7')
    })

    it('leaves anything unparseable alone rather than showing NaN', () => {
        expect(trimPrice('n/a')).toBe('n/a')
    })
})

describe('import API calls', () => {
    beforeEach(() => vi.restoreAllMocks())

    it('previews without sending anything that could write', async () => {
        const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { candidates: [] } } as never)

        await previewVseTariffImport({ zev: 'zev-1', url: 'https://werke.example.ch/t.json' })

        expect(postSpy).toHaveBeenCalledWith('/tariffs/imports/vse/preview/', {
            zev: 'zev-1',
            url: 'https://werke.example.ch/t.json',
        })
    })

    it('applies by key and digest, never by sending tariff data back', async () => {
        // The server re-fetches the document; the digest is what ties the
        // confirmation to the version the user reviewed.
        const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { created: [] } } as never)

        await applyVseTariffImport({
            zev: 'zev-1',
            url: 'https://werke.example.ch/t.json',
            selections: [
                { key: 'Netznutzung Basis (Arbeitspreis)@2027-01-01' },
                { key: 'Netznutzung Basis (Grundpreis)@2027-01-01', billing_mode: 'monthly_fee' },
            ],
            document_digest: 'a'.repeat(64),
            remember_url: true,
        })

        const [path, body] = postSpy.mock.calls[0]
        expect(path).toBe('/tariffs/imports/vse/apply/')
        expect(Object.keys(body as object).sort()).toEqual([
            'document_digest', 'remember_url', 'selections', 'url', 'zev',
        ])
    })
})
