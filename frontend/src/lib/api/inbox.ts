import type { DeliveredDocument, DeliveryResult, DocumentKind } from '../../types/api'
import { api } from './client'
import { fetchAllPages } from './pagination'

export interface InboxFilters {
  kinds?: DocumentKind[]
  zevId?: string
  participantId?: string
  year?: number
  includeSuperseded?: boolean
  /** Managers only; the server ignores it for a participant. */
  includeWithdrawn?: boolean
}

export async function listInboxDocuments(filters: InboxFilters = {}): Promise<DeliveredDocument[]> {
  return fetchAllPages<DeliveredDocument>('/inbox/documents/', {
    kind: filters.kinds?.length ? filters.kinds.join(',') : undefined,
    zev_id: filters.zevId,
    participant_id: filters.participantId,
    year: filters.year,
    include_superseded: filters.includeSuperseded === undefined ? undefined : String(filters.includeSuperseded),
    include_withdrawn: filters.includeWithdrawn ? 'true' : undefined,
  })
}

export async function getInboxDocument(id: string): Promise<DeliveredDocument> {
  const { data } = await api.get<DeliveredDocument>(`/inbox/documents/${id}/`)
  return data
}

export async function downloadInboxDocument(id: string, signal?: AbortSignal): Promise<Blob> {
  const { data } = await api.get<Blob>(`/inbox/documents/${id}/file/`, { responseType: 'blob', signal })
  return data
}

/** Open the delivered PDF in a new tab via an object URL; nothing is cached by the server. */
export async function openInboxDocument(id: string): Promise<void> {
  const blob = await downloadInboxDocument(id)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.target = '_blank'
  anchor.rel = 'noreferrer'
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}

export interface UploadInboxDocumentInput {
  zev: string
  title: string
  file: File
  audience: 'all' | 'selected'
  participantIds?: string[]
  /** Also email the participants a link (the bell notification is always sent). */
  notify?: boolean
}

export async function uploadInboxDocument(input: UploadInboxDocumentInput): Promise<DeliveryResult> {
  const body = new FormData()
  body.append('zev', input.zev)
  body.append('title', input.title)
  body.append('file', input.file)
  body.append('audience', input.audience)
  if (input.notify) body.append('notify', 'true')
  if (input.audience === 'selected') {
    for (const id of input.participantIds ?? []) body.append('participant_ids', id)
  }
  const { data } = await api.post<DeliveryResult>('/inbox/documents/', body)
  return data
}

export async function withdrawInboxDocument(id: string): Promise<DeliveredDocument> {
  const { data } = await api.post<DeliveredDocument>(`/inbox/documents/${id}/withdraw/`)
  return data
}

export interface IssueReportInput {
  zev: string
  year?: number
  participantIds?: string[]
  notify?: boolean
}

type IssueEndpoint = 'annual-statement' | 'financial-summary' | 'tariff-overview'

async function issue(endpoint: IssueEndpoint, input: IssueReportInput): Promise<DeliveryResult> {
  const { data } = await api.post<DeliveryResult>(`/inbox/issue/${endpoint}/`, {
    zev: input.zev,
    year: input.year,
    participant_ids: input.participantIds?.length ? input.participantIds : undefined,
    notify: input.notify || undefined,
  })
  return data
}

export const issueAnnualStatements = (input: IssueReportInput) => issue('annual-statement', input)
export const issueFinancialSummaries = (input: IssueReportInput) => issue('financial-summary', input)
export const issueTariffOverview = (input: Omit<IssueReportInput, 'year'>) => issue('tariff-overview', input)

/** Hand the participant's latest issued contract to their inbox. */
export async function deliverContract(participantId: string): Promise<DeliveryResult> {
  const { data } = await api.post<DeliveryResult>('/inbox/documents/deliver-contract/', { participant: participantId })
  return data
}
