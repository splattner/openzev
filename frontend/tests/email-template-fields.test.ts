import { describe, expect, it } from 'vitest'
import { EMAIL_TEMPLATE_FIELDS } from '../src/lib/emailTemplateFields'

describe('email template fields registry', () => {
    it('every template type has non-empty field set', () => {
        for (const [key, fields] of Object.entries(EMAIL_TEMPLATE_FIELDS)) {
            expect(fields.length, `${key} should have fields`).toBeGreaterThan(0)
        }
    })

    it('invoice_email contains due_date (regression for historical drift)', () => {
        const vars = EMAIL_TEMPLATE_FIELDS.invoice_email.map((f) => f.variable)
        expect(vars).toContain('{due_date}')
    })

    it('variables are unique per template type', () => {
        for (const [key, fields] of Object.entries(EMAIL_TEMPLATE_FIELDS)) {
            const vars = fields.map((f) => f.variable)
            expect(new Set(vars).size, `${key} has duplicate variables`).toBe(vars.length)
        }
    })
})
