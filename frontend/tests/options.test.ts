import { describe, expect, it } from 'vitest'
import { BILLING_INTERVAL_OPTIONS, METER_TYPE_OPTIONS, ZEV_TYPE_OPTIONS } from '../src/lib/options'
import type { BillingInterval } from '../src/lib/billingPeriod'
import type { MeteringPointInput, ZevInput } from '../src/types/api'

describe('options constants', () => {
    it('BILLING_INTERVAL_OPTIONS matches BillingInterval union', () => {
        const values = BILLING_INTERVAL_OPTIONS.map((o) => o.value)
        const expected: BillingInterval[] = ['monthly', 'quarterly', 'semi_annual', 'annual']
        // Canonical order: settings order (monthly -> annual)
        expect(values).toEqual(expected)
    })

    it('ZEV_TYPE_OPTIONS matches ZevInput zev_type union and canonical order (zev first)', () => {
        const values = ZEV_TYPE_OPTIONS.map((o) => o.value)
        const expected: ZevInput['zev_type'][] = ['zev', 'vzev']
        expect(values).toEqual(expected)
    })

    it('METER_TYPE_OPTIONS matches MeteringPointInput meter_type union', () => {
        const values = METER_TYPE_OPTIONS.map((o) => o.value)
        const expected: MeteringPointInput['meter_type'][] = ['consumption', 'production', 'bidirectional']
        expect(values).toEqual(expected)
    })

    it('every option has a non-empty labelKey', () => {
        for (const opt of [...BILLING_INTERVAL_OPTIONS, ...ZEV_TYPE_OPTIONS, ...METER_TYPE_OPTIONS]) {
            expect(opt.labelKey.length).toBeGreaterThan(0)
        }
    })
})
