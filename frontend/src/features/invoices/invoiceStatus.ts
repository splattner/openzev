/**
 * Single source for the "open invoice" concept: an invoice that has been
 * approved or sent but is not yet settled (paid/cancelled/draft).
 */
export const OPEN_INVOICE_STATUSES: readonly string[] = ['approved', 'sent']

export function isOpenInvoiceStatus(status: string): boolean {
  return OPEN_INVOICE_STATUSES.includes(status)
}

/** Badge CSS class for an invoice status, shared by all invoice tables. */
export function invoiceStatusBadgeClass(status: string): string {
  if (status === 'paid') return 'badge badge-success'
  if (status === 'cancelled') return 'badge badge-danger'
  if (isOpenInvoiceStatus(status)) return 'badge badge-info'
  return 'badge badge-neutral'
}
