/**
 * Single source for the "open invoice" concept: an invoice that has been
 * approved or sent but is not yet settled (paid/cancelled/draft).
 */
const OPEN_INVOICE_STATUSES: readonly string[] = ['approved', 'sent']

function isOpenInvoiceStatus(status: string): boolean {
  return OPEN_INVOICE_STATUSES.includes(status)
}

/**
 * Badge CSS class for an invoice status, shared by all invoice tables.
 * Approved wears the invoice document's own status pill (sage); sent is the
 * blue of something in transit; paid the settled green.
 */
export function invoiceStatusBadgeClass(status: string): string {
  if (status === 'paid') return 'badge badge-success'
  if (status === 'cancelled') return 'badge badge-danger'
  if (status === 'approved') return 'badge badge-brand'
  if (isOpenInvoiceStatus(status)) return 'badge badge-info'
  return 'badge badge-neutral'
}
