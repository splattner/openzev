import type { Invoice } from '../../types/api'
import { isOpenInvoiceStatus } from './invoiceStatus'

export function isInvoiceOverdue(
  invoice: Pick<Invoice, 'due_date' | 'status'>,
  today: string,
): boolean {
  if (!invoice.due_date) return false
  if (!isOpenInvoiceStatus(invoice.status)) return false
  return invoice.due_date < today
}

export function selectOpenInvoices(invoices: Invoice[]): Invoice[] {
  return invoices.filter((inv) => isOpenInvoiceStatus(inv.status))
}

export function sumTotalChf(invoices: Invoice[]): number {
  return invoices.reduce((sum, inv) => sum + Number.parseFloat(inv.total_chf ?? '0'), 0)
}
