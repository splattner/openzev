import {
  faFileContract,
  faFileInvoice,
  faFileLines,
  faFileSignature,
  faTags,
  faChartPie,
  type IconDefinition,
} from '@fortawesome/free-solid-svg-icons'
import type { DeliveredDocument, DocumentKind } from '../../types/api'

export const DOCUMENT_KINDS: readonly DocumentKind[] = [
  'invoice',
  'annual_statement',
  'financial_summary',
  'tariff_overview',
  'contract',
  'operator',
]

export const KIND_ICON: Record<DocumentKind, IconDefinition> = {
  invoice: faFileInvoice,
  contract: faFileContract,
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

export interface YearGroup {
  year: number
  documents: DeliveredDocument[]
}

/** Newest year first; within a year the incoming order (newest delivery first) is kept. */
export function groupByYear(documents: readonly DeliveredDocument[]): YearGroup[] {
  const groups = new Map<number, DeliveredDocument[]>()
  for (const document of documents) {
    const year = documentYear(document)
    const rows = groups.get(year)
    if (rows) rows.push(document)
    else groups.set(year, [document])
  }
  return [...groups.entries()]
    .sort(([a], [b]) => b - a)
    .map(([year, rows]) => ({ year, documents: rows }))
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
