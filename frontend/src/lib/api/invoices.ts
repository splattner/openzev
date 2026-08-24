import type {
  DashboardStats,
  EmailLog,
  EmailTemplateResponse,
  Invoice,
  InvoicePeriodOverview,
  PaginatedResponse,
  PdfTemplateResponse,
} from '../../types/api'
import { api } from './client'

export async function fetchInvoices(zevId?: string): Promise<PaginatedResponse<Invoice>> {
  const { data } = await api.get<PaginatedResponse<Invoice>>('/invoices/invoices/', {
    // Backend narrows by ?zev_id= on top of role scoping (issue #411); without it,
    // admins and multi-ZEV owners get every ZEV they can see.
    params: zevId ? { zev_id: zevId } : undefined,
  })
  return data
}

export async function fetchInvoice(invoiceId: string): Promise<Invoice> {
  const { data } = await api.get<Invoice>(`/invoices/invoices/${invoiceId}/`)
  return data
}

export async function generateInvoice(payload: {
  participant_id: string
  period_start: string
  period_end: string
}): Promise<Invoice> {
  const { data } = await api.post<Invoice>('/invoices/invoices/generate/', payload)
  return data
}

export async function generateInvoicesForZev(payload: {
  zev_id: string
  period_start: string
  period_end: string
}): Promise<{ detail: string; queued: boolean; participant_count: number }> {
  const { data } = await api.post<{ detail: string; queued: boolean; participant_count: number }>(
    '/invoices/invoices/generate-all/',
    payload,
  )
  return data
}

export async function approveAllInvoices(payload: {
  zev_id: string
  period_start: string
  period_end: string
}): Promise<{ approved: number }> {
  const { data } = await api.post<{ approved: number }>('/invoices/invoices/approve-all/', payload)
  return data
}

export async function sendAllInvoices(payload: {
  zev_id: string
  period_start: string
  period_end: string
}): Promise<{ queued: number; skipped: number }> {
  const { data } = await api.post<{ queued: number; skipped: number }>('/invoices/invoices/send-all/', payload)
  return data
}

export async function generateAllPdfs(payload: {
  zev_id: string
  period_start: string
  period_end: string
}): Promise<{ detail: string; queued: boolean; invoice_count: number }> {
  const { data } = await api.post<{ detail: string; queued: boolean; invoice_count: number }>(
    '/invoices/invoices/generate-pdfs-all/',
    payload,
  )
  return data
}

export async function downloadAllPdfs(payload: {
  zev_id: string
  period_start: string
  period_end: string
}): Promise<Blob> {
  const { data } = await api.post('/invoices/invoices/download-pdfs/', payload, { responseType: 'blob' })
  return data as Blob
}

export async function downloadAnnualStatement(params: {
  year: number
  participant_id?: string
  zev_id?: string
}): Promise<Blob> {
  const { data } = await api.get('/invoices/invoices/annual-statement/', {
    params,
    responseType: 'blob',
  })
  return data as Blob
}

export async function downloadAllAnnualStatements(params: {
  year: number
  zev_id: string
}): Promise<Blob> {
  const { data } = await api.get('/invoices/invoices/annual-statements-zip/', {
    params,
    responseType: 'blob',
  })
  return data as Blob
}

export async function downloadFinancialSummary(params: {
  year: number
  zev_id?: string
  participant_id?: string
}): Promise<Blob> {
  const { data } = await api.get('/invoices/invoices/financial-summary/', {
    params,
    responseType: 'blob',
  })
  return data as Blob
}

export async function fetchInvoicePeriodOverview(params: {
  zev_id: string
  period_start: string
  period_end: string
}): Promise<InvoicePeriodOverview> {
  const { data } = await api.get<InvoicePeriodOverview>('/invoices/invoices/period-overview/', { params })
  return data
}

export async function generateInvoicePdf(invoiceId: string): Promise<{ pdf_url: string }> {
  const { data } = await api.post<{ pdf_url: string }>(`/invoices/invoices/${invoiceId}/generate-pdf/`)
  return data
}

/** Fetch the authenticated PDF blob via the API (not /media/). */
export async function fetchInvoicePdfBlob(invoiceId: string): Promise<Blob> {
  const response = await api.get<Blob>(`/invoices/invoices/${invoiceId}/pdf/`, {
    responseType: 'blob',
  })
  return response.data
}

/** Fetch the PDF blob and open it in a new tab via object URL. */
export async function openInvoicePdf(invoiceId: string): Promise<void> {
  const blob = await fetchInvoicePdfBlob(invoiceId)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.target = '_blank'
  anchor.rel = 'noreferrer'
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

export async function sendInvoiceEmail(invoiceId: string, email?: string): Promise<{ detail: string }> {
  const { data } = await api.post<{ detail: string }>(`/invoices/invoices/${invoiceId}/send-email/`, { email })
  return data
}

export async function approveInvoice(invoiceId: string): Promise<Invoice> {
  const { data } = await api.post<Invoice>(`/invoices/invoices/${invoiceId}/approve/`)
  return data
}

export async function markInvoiceSent(invoiceId: string): Promise<Invoice> {
  const { data } = await api.post<Invoice>(`/invoices/invoices/${invoiceId}/mark-sent/`)
  return data
}

export async function markInvoicePaid(invoiceId: string): Promise<Invoice> {
  const { data } = await api.post<Invoice>(`/invoices/invoices/${invoiceId}/mark-paid/`)
  return data
}

export async function deleteInvoice(invoiceId: string): Promise<void> {
  await api.delete(`/invoices/invoices/${invoiceId}/`)
}

export async function fetchEmailLogs(invoiceId: string): Promise<EmailLog[]> {
  const { data } = await api.get<{ email_logs: EmailLog[] }>(`/invoices/invoices/${invoiceId}/`)
  return data.email_logs || []
}

export async function retryFailedEmail(invoiceId: string, emailLogId: string): Promise<{ detail: string }> {
  const { data } = await api.post<{ detail: string }>(`/invoices/invoices/${invoiceId}/retry-email/${emailLogId}/`)
  return data
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  const { data } = await api.get<DashboardStats>('/invoices/invoices/dashboard/')
  return data
}

export async function fetchInvoicePdfTemplate(): Promise<PdfTemplateResponse> {
  const { data } = await api.get<PdfTemplateResponse>('/invoices/invoices/pdf-template/')
  return data
}

export async function updateInvoicePdfTemplate(content: string): Promise<PdfTemplateResponse> {
  const { data } = await api.patch<PdfTemplateResponse>('/invoices/invoices/pdf-template/', { content })
  return data
}

export async function fetchContractPdfTemplate(): Promise<PdfTemplateResponse> {
  const { data } = await api.get<PdfTemplateResponse>('/invoices/invoices/contract-pdf-template/')
  return data
}

export async function updateContractPdfTemplate(content: string): Promise<PdfTemplateResponse> {
  const { data } = await api.patch<PdfTemplateResponse>('/invoices/invoices/contract-pdf-template/', { content })
  return data
}

export async function resetInvoicePdfTemplate(): Promise<PdfTemplateResponse> {
  const { data } = await api.delete<PdfTemplateResponse>('/invoices/invoices/pdf-template/')
  return data
}

export async function resetContractPdfTemplate(): Promise<PdfTemplateResponse> {
  const { data } = await api.delete<PdfTemplateResponse>('/invoices/invoices/contract-pdf-template/')
  return data
}

export async function fetchAnnualStatementPdfTemplate(): Promise<PdfTemplateResponse> {
  const { data } = await api.get<PdfTemplateResponse>('/invoices/invoices/annual-statement-pdf-template/')
  return data
}

export async function updateAnnualStatementPdfTemplate(content: string): Promise<PdfTemplateResponse> {
  const { data } = await api.patch<PdfTemplateResponse>('/invoices/invoices/annual-statement-pdf-template/', { content })
  return data
}

export async function resetAnnualStatementPdfTemplate(): Promise<PdfTemplateResponse> {
  const { data } = await api.delete<PdfTemplateResponse>('/invoices/invoices/annual-statement-pdf-template/')
  return data
}

/** Real-PDF preview: runs the same WeasyPrint pipeline as issued documents and
 * returns the raw bytes as a Blob for an object-URL iframe. */
export async function previewPdfTemplateBlob(
  content: string,
  templateType: 'invoice' | 'contract' | 'annual_statement',
  signal?: AbortSignal,
): Promise<Blob> {
  const response = await api.post(
    '/invoices/invoices/preview-pdf-template/',
    { content, template_type: templateType, output: 'pdf' },
    { responseType: 'blob', headers: { Accept: 'application/pdf' }, signal },
  )
  return response.data as Blob
}

export async function fetchEmailTemplate(templateKey: string): Promise<EmailTemplateResponse> {
  const { data } = await api.get<EmailTemplateResponse>(`/invoices/invoices/email-template/${templateKey}/`)
  return data
}

export async function updateEmailTemplate(templateKey: string, subject: string, body: string): Promise<EmailTemplateResponse> {
  const { data } = await api.patch<EmailTemplateResponse>(`/invoices/invoices/email-template/${templateKey}/`, { subject, body })
  return data
}

export async function resetEmailTemplate(templateKey: string): Promise<EmailTemplateResponse> {
  const { data } = await api.delete<EmailTemplateResponse>(`/invoices/invoices/email-template/${templateKey}/`)
  return data
}
