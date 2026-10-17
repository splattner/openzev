import { describe, it, expect } from 'vitest'
import {
    bearersLabel,
    chargeFieldErrors,
    chargeInputFrom,
    chargeToValues,
    clampDate,
    emptyChargeValues,
    type ChargeFormValues,
} from '../src/features/charges/chargeForm'
import { stepDetailText } from '../src/features/overview/readinessPresentation'
import type { Charge, ReadinessStep } from '../src/types/api'

const t = ((key: string, options?: Record<string, unknown>) =>
    options ? `${key}:${JSON.stringify(options)}` : key) as never

const filled = (overrides: Partial<ChargeFormValues> = {}): ChargeFormValues => ({
    ...emptyChargeValues('2026-01-15'),
    description: ' Porto ',
    amount: '12.5',
    ...overrides,
})

describe('chargeFieldErrors', () => {
    it('accepts a complete charge for everyone', () => {
        expect(chargeFieldErrors(filled())).toEqual({})
    })

    it('flags a blank description, a non-positive amount and a missing date', () => {
        expect(chargeFieldErrors(filled({ description: '  ', amount: '0', chargeDate: null }))).toEqual({
            description: true,
            amount: true,
            chargeDate: true,
        })
        expect(chargeFieldErrors(filled({ amount: '' })).amount).toBe(true)
    })

    it('requires a participant once the charge is for selected participants', () => {
        expect(chargeFieldErrors(filled({ allocation: 'selected_participants' })).participants).toBe(true)
        expect(
            chargeFieldErrors(filled({ allocation: 'selected_participants', participants: ['p1'] })).participants,
        ).toBeUndefined()
    })
})

describe('chargeInputFrom', () => {
    it('is null while the form is incomplete, so no preview is asked for', () => {
        expect(chargeInputFrom(filled({ amount: '' }), 'zev-1')).toBeNull()
    })

    it('trims, formats the amount to centimes and scopes it to the community', () => {
        expect(chargeInputFrom(filled(), 'zev-1')).toEqual({
            zev: 'zev-1',
            description: 'Porto',
            amount_chf: '12.50',
            charge_date: '2026-01-15',
            allocation: 'all_participants',
            split_key: 'equal',
            vat_treatment: 'taxable',
            participants: [],
        })
    })

    it('sends no participants for a charge for everyone, even if some were ticked before', () => {
        expect(chargeInputFrom(filled({ participants: ['p1'] }), 'zev-1')?.participants).toEqual([])
        expect(
            chargeInputFrom(filled({ allocation: 'selected_participants', participants: ['p1'] }), 'zev-1')?.participants,
        ).toEqual(['p1'])
    })
})

describe('chargeToValues', () => {
    it('round-trips a stored charge into the form', () => {
        const charge: Charge = {
            id: 'c1', zev: 'zev-1', description: 'Reparatur', amount_chf: '80.00', charge_date: '2026-02-03',
            allocation: 'selected_participants', split_key: 'weight', vat_treatment: 'pass_through',
            participants: ['p1'], is_locked: false, created_at: '', updated_at: '',
        }

        expect(chargeInputFrom(chargeToValues(charge), 'zev-1')).toMatchObject({
            description: 'Reparatur', amount_chf: '80.00', split_key: 'weight', vat_treatment: 'pass_through', participants: ['p1'],
        })
    })
})

describe('bearersLabel', () => {
    const names = new Map([['p1', 'Alice Muster']])

    it('names a single bearer and counts several', () => {
        expect(bearersLabel({ allocation: 'all_participants', participants: [] }, names, t)).toBe('pages.charges.bearers.all')
        expect(bearersLabel({ allocation: 'selected_participants', participants: ['p1'] }, names, t)).toBe('Alice Muster')
        expect(bearersLabel({ allocation: 'selected_participants', participants: ['p1', 'p2'] }, names, t))
            .toBe('pages.charges.bearers.selected:{"count":2}')
    })
})

describe('readiness charges step', () => {
    const step = (overrides: Partial<ReadinessStep>): ReadinessStep => ({
        key: 'charges', status: 'done', count: 0, ...overrides,
    } as ReadinessStep)

    it('asks to regenerate stale drafts', () => {
        expect(stepDetailText(step({ status: 'todo', count: 1, detail_data: { stale_drafts: 2 } }), t))
            .toBe('pages.dashboard.cockpit.stepDetails.chargesTodo:{"count":2}')
    })

    it('names charges nobody can be billed for', () => {
        expect(stepDetailText(step({ status: 'warn', count: 1, detail_data: { unbilled_charges: ['Porto'], more_unbilled: 1 } }), t))
            .toBe('pages.dashboard.cockpit.stepDetails.chargesWarn:{"count":2,"names":"Porto"}')
    })

    it('says nothing when everything is billed', () => {
        expect(stepDetailText(step({ status: 'done', count: 3 }), t)).toBeNull()
    })
})

describe('clampDate', () => {
    it('keeps a day inside the period and pulls the others to its edges', () => {
        expect(clampDate('2026-11-05', '2026-10-01', '2026-12-31')).toBe('2026-11-05')
        expect(clampDate('2026-09-30', '2026-10-01', '2026-12-31')).toBe('2026-10-01')
        expect(clampDate('2027-01-01', '2026-10-01', '2026-12-31')).toBe('2026-12-31')
    })
})
