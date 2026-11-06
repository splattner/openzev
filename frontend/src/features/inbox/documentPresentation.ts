import {
  faFileContract,
  faFileInvoice,
  faFileLines,
  faFileSignature,
  faReceipt,
  faTags,
  faChartPie,
  type IconDefinition,
} from '@fortawesome/free-solid-svg-icons'
import type { DeliveredDocument, DocumentKind } from '../../types/api'

export const DOCUMENT_KINDS: readonly DocumentKind[] = [
  'invoice',
  'credit_note',
  'annual_statement',
  'financial_summary',
  'tariff_overview',
  'contract',
  'operator',
]

export const KIND_ICON: Record<DocumentKind, IconDefinition> = {
  invoice: faFileInvoice,
  contract: faFileContract,
  credit_note: faReceipt,
  annual_statement: faFileSignature,
  financial_summary: faChartPie,
  tariff_overview: faTags,
  operator: faFileLines,
}

/** What a row says about its own standing; a document is never deleted, only marked. */
export type DocumentStanding = 'withdrawn' | 'cancelled' | 'superseded' | null

export function documentStanding(document: Pick<DeliveredDocument, 'withdrawn_at' | 'invoice_status' | 'superseded_at'>): DocumentStanding {
  if (document.withdrawn_at) return 'withdrawn'
  if (document.invoice_status === 'cancelled') return 'cancelled'
  if (document.superseded_at) return 'superseded'
  return null
}

/** The year a document belongs to: its period when it has one, else the year it was delivered. */
export function documentYear(document: Pick<DeliveredDocument, 'period_start' | 'delivered_at'>): number {
  return Number((document.period_start ?? document.delivered_at).slice(0, 4))
}

/** What the outbox shows once for everybody it reached: the same file, sent in one batch. */
const BROADCAST_KINDS: readonly DocumentKind[] = ['operator', 'tariff_overview']

/** One line of the manager's outbox: a document, or a broadcast with the rows it produced. */
export type OutboxEntry = { key: string; documents: DeliveredDocument[] }

/**
 * Groups the rows of one delivery of a notice or tariff overview into a single entry, so one
 * upload to a community of seven is one line, not seven. Everything else (invoices, statements,
 * contracts, and a broadcast that reached one person) stays one line per row. Order is kept: an
 * entry sits where its first row was.
 */
export function groupOutbox(documents: readonly DeliveredDocument[]): OutboxEntry[] {
  const entries: OutboxEntry[] = []
  const batches = new Map<string, OutboxEntry>()
  for (const document of documents) {
    if (document.batch_id && BROADCAST_KINDS.includes(document.kind)) {
      const key = `${document.kind}:${document.batch_id}`
      const entry = batches.get(key)
      if (entry) {
        entry.documents.push(document)
        continue
      }
      const created = { key, documents: [document] }
      batches.set(key, created)
      entries.push(created)
      continue
    }
    entries.push({ key: document.id, documents: [document] })
  }
  return entries
}

export function countByKind(documents: readonly DeliveredDocument[]): Record<DocumentKind, number> {
  const counts = Object.fromEntries(DOCUMENT_KINDS.map((kind) => [kind, 0])) as Record<DocumentKind, number>
  for (const document of documents) counts[document.kind] += 1
  return counts
}

export function formatFileSize(bytes: number | null): string {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024

export type UploadFileProblem = 'empty' | 'tooLarge' | 'notPdf' | null

/** An advisory check only; the server decides by the file's content. */
export function uploadFileProblem(file: Pick<File, 'name' | 'size' | 'type'>): UploadFileProblem {
  if (file.size === 0) return 'empty'
  if (file.size > MAX_UPLOAD_BYTES) return 'tooLarge'
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) return 'notPdf'
  return null
}
