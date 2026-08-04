import type { TransferSection, TransferSectionName } from '../../features/zev/transferSections'
import { api } from './client'

export type ArchiveManifest = {
  format_version: number
  exported_at: string
  source_instance: string
  sections: TransferSectionName[]
  counts: Record<string, number>
  source_zev: { id: string; name: string }
}

export type ImportResult = {
  zev_id: string
  zev_name: string
  sections: TransferSectionName[]
  counts: Record<string, number>
}

export type ImportEntryError = {
  section: TransferSectionName
  position: number | null
  label: string
  errors: Record<string, string[]>
}

export async function fetchTransferSections(): Promise<TransferSection[]> {
  const { data } = await api.get<{ sections: TransferSection[] }>('/zev/zevs/transfer-sections/')
  return data.sections
}

/**
 * Download the archive as a Blob.
 *
 * `responseType: 'blob'` matters: axios would otherwise try to decode the ZIP
 * as text and hand back a corrupted string.
 */
export async function exportZevArchive(
  zevId: string,
  sections: TransferSectionName[],
): Promise<{ blob: Blob; filename: string }> {
  const response = await api.get(`/zev/zevs/${zevId}/export/`, {
    params: { sections: sections.join(',') },
    responseType: 'blob',
  })
  return {
    blob: response.data as Blob,
    filename: filenameFromDisposition(response.headers['content-disposition']) ?? 'openzev-export.zip',
  }
}

/** Read an archive's manifest without importing it. */
export async function inspectZevArchive(file: File): Promise<ArchiveManifest> {
  const body = new FormData()
  body.append('file', file)
  const { data } = await api.post<ArchiveManifest>('/zev/zevs/inspect-archive/', body)
  return data
}

export async function importZevArchive(
  file: File,
  sections: TransferSectionName[],
  name: string,
): Promise<ImportResult> {
  const body = new FormData()
  body.append('file', file)
  body.append('sections', sections.join(','))
  if (name.trim()) {
    body.append('name', name.trim())
  }
  const { data } = await api.post<ImportResult>('/zev/zevs/import-archive/', body)
  return data
}

export function filenameFromDisposition(header: unknown): string | null {
  if (typeof header !== 'string') return null
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header)
  return match ? decodeURIComponent(match[1]) : null
}

/**
 * A failed export answers with a JSON body, but the request asked for a
 * Blob — so axios hands back the error body as a Blob too, and the generic
 * error formatter sees nothing useful. This reads it back as text.
 */
export async function readBlobError(payload: unknown): Promise<string | null> {
  if (!(payload instanceof Blob)) return null
  try {
    const parsed = JSON.parse(await payload.text()) as { detail?: string }
    return parsed.detail ?? null
  } catch {
    return null
  }
}
