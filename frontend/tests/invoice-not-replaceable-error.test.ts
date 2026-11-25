import { describe, expect, it } from 'vitest'
import { invoiceNotReplaceablePayload } from '../src/lib/api/errors'

const axiosError = (data: unknown) => ({ isAxiosError: true, response: { status: 409, data } })

describe('invoiceNotReplaceablePayload', () => {
  it('reads the blocker reason and invoice number for a translated message', () => {
    expect(invoiceNotReplaceablePayload(axiosError({
      code: 'invoice_not_replaceable', reason: 'partial_overlap', invoice_number: 'OZV-7', error: 'Replacement period …',
    }))).toEqual({ code: 'invoice_not_replaceable', reason: 'partial_overlap', invoice_number: 'OZV-7' })
  })

  it('leaves other errors and unknown reasons to the generic message', () => {
    expect(invoiceNotReplaceablePayload(axiosError({ error: 'Invoice generation failed.' }))).toBeNull()
    expect(invoiceNotReplaceablePayload(axiosError({ code: 'invoice_not_replaceable', reason: 'other', invoice_number: 'OZV-7' }))).toBeNull()
    expect(invoiceNotReplaceablePayload(new Error('network'))).toBeNull()
  })
})
