import { describe, expect, it } from 'vitest'
import {
  countByKind,
  documentStanding,
  documentYear,
  formatFileSize,
  uploadFileProblem,
} from '../src/features/inbox/documentPresentation'
import { issueYears } from '../src/features/inbox/IssueReportsDialog'
import type { DeliveredDocument } from '../src/types/api'

function doc(overrides: Partial<DeliveredDocument> = {}): DeliveredDocument {
  return {
    id: 'd', zev: 'z', zev_name: 'Z', participant: 'p', participant_name: 'P', kind: 'operator', title: 'T',
    document_number: '', period_start: null, period_end: null, file_name: 'a.pdf', size_bytes: 10, sha256: '',
    delivered_at: '2026-03-04T10:00:00Z', delivered_by_name: null, superseded_at: null, superseded_by: null,
    withdrawn_at: null, batch_id: null, invoice: null, invoice_status: null, contract_issue: null,
    ...overrides,
  }
}

describe('documentYear', () => {
  it('uses the period when there is one, else the delivery year', () => {
    expect(documentYear(doc({ period_start: '2025-01-01' }))).toBe(2025)
    expect(documentYear(doc())).toBe(2026)
  })
})

describe('documentStanding', () => {
  it('lets a withdrawal outrank a cancellation, and a cancellation a supersession', () => {
    expect(documentStanding(doc({ withdrawn_at: 'x', invoice_status: 'cancelled', superseded_at: 'x' }))).toBe('withdrawn')
    expect(documentStanding(doc({ invoice_status: 'cancelled', superseded_at: 'x' }))).toBe('cancelled')
    expect(documentStanding(doc({ superseded_at: 'x' }))).toBe('superseded')
    expect(documentStanding(doc({ invoice_status: 'sent' }))).toBeNull()
  })
})

describe('countByKind', () => {
  it('counts every kind, including those with none', () => {
    const counts = countByKind([doc({ kind: 'invoice' }), doc({ kind: 'invoice' }), doc({ kind: 'contract' })])
    expect(counts.invoice).toBe(2)
    expect(counts.contract).toBe(1)
    expect(counts.tariff_overview).toBe(0)
    expect(counts.credit_note).toBe(0)
  })
})

describe('uploadFileProblem', () => {
  const file = (name: string, size: number, type = 'application/pdf') => ({ name, size, type })

  it('accepts a PDF within the limit', () => {
    expect(uploadFileProblem(file('rules.pdf', 1000))).toBeNull()
    expect(uploadFileProblem(file('RULES.PDF', 1000, ''))).toBeNull()
  })

  it('names what is wrong, empty first and oversize before type', () => {
    expect(uploadFileProblem(file('a.pdf', 0))).toBe('empty')
    expect(uploadFileProblem(file('a.pdf', 11 * 1024 * 1024))).toBe('tooLarge')
    expect(uploadFileProblem(file('a.png', 10, 'image/png'))).toBe('notPdf')
  })
})

describe('formatFileSize', () => {
  it('scales the unit', () => {
    expect(formatFileSize(null)).toBe('')
    expect(formatFileSize(512)).toBe('512 B')
    expect(formatFileSize(2048)).toBe('2 KB')
    expect(formatFileSize(10 * 1024 * 1024)).toBe('10.0 MB')
  })
})

describe('issueYears', () => {
  it('lists this year and the five before, newest first', () => {
    expect(issueYears('2026-11-05')).toEqual([2026, 2025, 2024, 2023, 2022, 2021])
  })
})
