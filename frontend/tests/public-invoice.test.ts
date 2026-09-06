import { describe, it, expect, vi, beforeEach } from 'vitest'

import { fetchPublicInvoice, publicInvoicePdfUrl } from '../src/lib/api/public'
import { api } from '../src/lib/api/client'
import { groupItemsByCategory } from '../src/features/publicInvoice/grouping'
import type { PublicInvoiceItem } from '../src/types/api'

describe('publicInvoicePdfUrl', () => {
    it('carries the prefix in the path and the secret as a parameter', () => {
        const url = publicInvoicePdfUrl('abc123', 'sec-ret')

        expect(url).toContain('/public/invoices/abc123/pdf/')
        expect(url).toContain('s=sec-ret')
    })

    it('encodes a secret containing URL-significant characters', () => {
        // token_urlsafe never emits these, but the page must not silently
        // mangle a link if that ever changes.
        expect(publicInvoicePdfUrl('abc', 'a+b/c=d&e')).toContain(
            's=a%2Bb%2Fc%3Dd%26e',
        )
    })
})

describe('fetchPublicInvoice', () => {
    beforeEach(() => vi.restoreAllMocks())

    it('sends the secret as a query parameter, never in the path', async () => {
        const get = vi.spyOn(api, 'get').mockResolvedValue({ data: { invoice_number: 'X' } })

        await fetchPublicInvoice('abc123', 'sec-ret')

        expect(get).toHaveBeenCalledWith('/public/invoices/abc123/', {
            params: { s: 'sec-ret' },
        })
    })

    it('propagates a 404 rather than translating it', async () => {
        // Every failure is a 404 by design; the page turns all of them into one
        // "not valid" state, so the client must not classify them further.
        vi.spyOn(api, 'get').mockRejectedValue({ response: { status: 404 } })

        await expect(fetchPublicInvoice('abc', 'bad')).rejects.toMatchObject({
            response: { status: 404 },
        })
    })
})

describe('groupItemsByCategory', () => {
    const item = (category: PublicInvoiceItem['category'], description: string) =>
        ({ category, description, quantity: '1', unit: 'kWh', total_chf: '1.00' }) as PublicInvoiceItem

    it('orders categories the way the invoice PDF does', () => {
        const groups = groupItemsByCategory([
            item('metering', 'Meter'),
            item('energy', 'Solar'),
            item('levies', 'KEV'),
            item('grid_fees', 'Netznutzung'),
        ])

        expect(groups.map((g) => g.category)).toEqual([
            'energy',
            'grid_fees',
            'levies',
            'metering',
        ])
    })

    it('omits categories with no lines rather than rendering empty headings', () => {
        const groups = groupItemsByCategory([item('energy', 'Solar')])

        expect(groups).toHaveLength(1)
        expect(groups[0].items.map((i) => i.description)).toEqual(['Solar'])
    })

    it('keeps several lines within one category', () => {
        const groups = groupItemsByCategory([
            item('energy', 'Solar'),
            item('energy', 'Netzstrom'),
        ])

        expect(groups[0].items).toHaveLength(2)
    })

    it('returns nothing for an invoice with no lines', () => {
        expect(groupItemsByCategory([])).toEqual([])
    })
})
