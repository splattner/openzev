import type {
    BackupDestination,
    BackupDestinationInput,
    BackupJob,
    BackupJobInput,
    BackupStatus,
} from '../../types/api'
import { api } from './client'
import { fetchAllPages } from './pagination'

export async function fetchBackupDestinations(): Promise<BackupDestination[]> {
    return fetchAllPages<BackupDestination>('/backups/destinations/')
}

export async function createBackupDestination(payload: BackupDestinationInput): Promise<BackupDestination> {
    const { data } = await api.post<BackupDestination>('/backups/destinations/', payload)
    return data
}

export async function updateBackupDestination(
    id: string,
    payload: Partial<BackupDestinationInput>,
): Promise<BackupDestination> {
    const { data } = await api.patch<BackupDestination>(`/backups/destinations/${id}/`, payload)
    return data
}

export async function deleteBackupDestination(id: string): Promise<void> {
    await api.delete(`/backups/destinations/${id}/`)
}

/** Writes and deletes a probe object; rejects with the provider's explanation when unusable. */
export async function testBackupDestination(id: string): Promise<void> {
    await api.post(`/backups/destinations/${id}/test/`)
}

export async function fetchBackupJobs(): Promise<BackupJob[]> {
    const { data } = await api.get<BackupJob[]>('/backups/jobs/')
    return data
}

/** Queue a backup; resolves with the queued job. */
export async function createBackupJob(payload: BackupJobInput): Promise<BackupJob> {
    const { data } = await api.post<BackupJob>('/backups/jobs/', payload)
    return data
}

/** Download a finished archive from a local destination as a blob. */
export async function downloadBackupArtifact(jobId: string): Promise<Blob> {
    const { data } = await api.get(`/backups/jobs/${jobId}/download/`, { responseType: 'blob' })
    return data as Blob
}

export async function fetchBackupStatus(): Promise<BackupStatus> {
    const { data } = await api.get<BackupStatus>('/backups/status/')
    return data
}
