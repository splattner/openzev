import { describe, expect, it, vi } from 'vitest'
import { grossRate, ingestUrl, statusTone, withheldReasonKey } from '../src/lib/supplementary'
import type { GrossEnergy } from '../src/types/api'

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

describe('grossRate', () => {
    it('returns the requested rate', () => {
        expect(grossRate(gross())).toBe(75)
        expect(grossRate(gross(), 'self_sufficiency')).toBe(75)
        expect(grossRate(gross(), 'self_consumption')).toBe(25)
    })

    it('is null without figures', () => {
        expect(grossRate(null)).toBeNull()
        expect(grossRate(undefined)).toBeNull()
    })

    it('never shows a withheld rate, even if a number slipped through', () => {
        expect(grossRate(gross({ rates_withheld_reason: 'low_coverage' }))).toBeNull()
        expect(grossRate(gross({ rates_withheld_reason: 'no_data', self_sufficiency_rate: 12 }))).toBeNull()
    })

    it('keeps a legitimate zero, which is not a missing rate', () => {
        expect(grossRate(gross({ self_sufficiency_rate: 0 }))).toBe(0)
    })
})

describe('withheldReasonKey', () => {
    it('names the reason a rate is a dash', () => {
        expect(withheldReasonKey(gross({ rates_withheld_reason: 'low_coverage' }))).toBe('supplementary.withheld.lowCoverage')
        expect(withheldReasonKey(gross({ rates_withheld_reason: 'no_data' }))).toBe('supplementary.withheld.noData')
    })

    it('has none when there is a rate or no figures', () => {
        expect(withheldReasonKey(gross())).toBeNull()
        expect(withheldReasonKey(null)).toBeNull()
    })
})

describe('statusTone', () => {
    it('maps each status to a tone', () => {
        expect(statusTone('ok')).toBe('success')
        expect(statusTone('error')).toBe('warning')
        expect(statusTone('reconnect_required')).toBe('danger')
        expect(statusTone('pending')).toBe('neutral')
        expect(statusTone('disabled')).toBe('neutral')
        expect(statusTone(null)).toBe('neutral')
    })
})

describe('ingestUrl', () => {
    it('is an absolute address a push client can use', () => {
        expect(ingestUrl('https://zev.example.ch')).toMatch(/^https?:\/\/.+\/metering\/supplementary\/ingest\/$/)
    })

    it('puts a relative API base on this origin', async () => {
        vi.resetModules()
        vi.doMock('../src/lib/api/client', () => ({ API_BASE_URL: '/api/v1', api: {} }))
        const { ingestUrl: relative } = await import('../src/lib/supplementary')
        expect(relative('https://zev.example.ch')).toBe('https://zev.example.ch/api/v1/metering/supplementary/ingest/')
        vi.doUnmock('../src/lib/api/client')
        vi.resetModules()
    })

    it('keeps an absolute API base as it is', async () => {
        vi.resetModules()
        vi.doMock('../src/lib/api/client', () => ({ API_BASE_URL: 'https://api.example.ch/v1/', api: {} }))
        const { ingestUrl: absolute } = await import('../src/lib/supplementary')
        expect(absolute('https://zev.example.ch')).toBe('https://api.example.ch/v1/metering/supplementary/ingest/')
        vi.doUnmock('../src/lib/api/client')
        vi.resetModules()
    })
})
