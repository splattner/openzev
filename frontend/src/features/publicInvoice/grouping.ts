import type { PublicInvoiceItem } from '../../types/api'

/** Same order the invoice PDF and the tariff overview group their lines in. */
export const CATEGORY_ORDER: PublicInvoiceItem['category'][] = [
    'energy',
    'grid_fees',
    'levies',
    'metering',
]

export interface PublicInvoiceGroup {
    category: PublicInvoiceItem['category']
    items: PublicInvoiceItem[]
}

/**
 * Line items grouped by category, in the invoice's canonical order.
 *
 * Extracted from the page for the same reason `tariffOverview.ts` was: the
 * rendering is browser plumbing, this is the part with a right answer. Empty
 * categories are dropped rather than rendered as bare headings, matching what
 * the PDF does.
 */
export function groupItemsByCategory(items: PublicInvoiceItem[]): PublicInvoiceGroup[] {
    return CATEGORY_ORDER.map((category) => ({
        category,
        items: items.filter((item) => item.category === category),
    })).filter((group) => group.items.length > 0)
}
