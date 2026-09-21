import type {
    BackupDestination,
    BackupDestinationInput,
    BackupDestinationKind,
    BackupJob,
    BackupManifest,
} from '../../types/api'

/** Statuses during which a job's row is still changing, so the list keeps polling. */
export function hasActiveJob(jobs: BackupJob[] | undefined): boolean {
    return (jobs ?? []).some((job) => job.status === 'queued' || job.status === 'running')
}

export interface DestinationFormState {
    name: string
    kind: BackupDestinationKind
    enabled: boolean
    path: string
    bucket: string
    prefix: string
    region: string
    endpoint_url: string
    access_key_id: string
    server_side_encryption: string
    /** Typed by the admin; never pre-filled, because the server never returns it. */
    secret_access_key: string
    /** Ask the server to forget the stored secret. */
    remove_secret: boolean
}

export const EMPTY_DESTINATION_FORM: DestinationFormState = {
    name: '',
    kind: 'local',
    enabled: true,
    path: '',
    bucket: '',
    prefix: '',
    region: '',
    endpoint_url: '',
    access_key_id: '',
    server_side_encryption: 'AES256',
    secret_access_key: '',
    remove_secret: false,
}

export function destinationToForm(destination: BackupDestination): DestinationFormState {
    return {
        name: destination.name,
        kind: destination.kind,
        enabled: destination.enabled,
        path: destination.path,
        bucket: destination.bucket,
        prefix: destination.prefix,
        region: destination.region,
        endpoint_url: destination.endpoint_url,
        access_key_id: destination.access_key_id,
        server_side_encryption: destination.server_side_encryption,
        secret_access_key: '',
        remove_secret: false,
    }
}

/**
 * The request body for a destination form.
 *
 * Fields that belong to the other kind are sent empty, so switching a
 * destination's kind cannot leave stale values behind for the server to reject.
 * The secret follows the API's contract: absent leaves a stored one alone (so an
 * edit that never touches the field cannot wipe a credential), a value replaces
 * it, and `''` clears it.
 */
export function buildDestinationPayload(
    form: DestinationFormState,
    existing?: BackupDestination,
): BackupDestinationInput {
    const base = { name: form.name.trim(), kind: form.kind, enabled: form.enabled }

    if (form.kind === 'local') {
        const payload: BackupDestinationInput = {
            ...base,
            path: form.path.trim(),
            bucket: '',
            prefix: '',
            region: '',
            endpoint_url: '',
            access_key_id: '',
            server_side_encryption: form.server_side_encryption,
        }
        // Switching an S3 destination to local: the stored secret must go too.
        if (existing?.has_secret_access_key) payload.secret_access_key = ''
        return payload
    }

    const payload: BackupDestinationInput = {
        ...base,
        path: '',
        bucket: form.bucket.trim(),
        prefix: form.prefix.trim().replace(/^\/+/, ''),
        region: form.region.trim(),
        endpoint_url: form.endpoint_url.trim(),
        access_key_id: form.access_key_id.trim(),
        server_side_encryption: form.server_side_encryption,
    }
    if (form.secret_access_key) {
        payload.secret_access_key = form.secret_access_key
    } else if (form.remove_secret) {
        payload.secret_access_key = ''
    }
    return payload
}

/** The human-readable target of a destination: a directory, or `bucket/prefix` at an endpoint. */
export function destinationTarget(destination: BackupDestination): string {
    if (destination.kind === 'local') return destination.path
    const key = [destination.bucket, destination.prefix.replace(/^\/+|\/+$/g, '')].filter(Boolean).join('/')
    return destination.endpoint_url ? `${key} @ ${destination.endpoint_url}` : key
}

/** A manifest, or `null` while the job has not produced one (it is `{}` until completion). */
export function readManifest(job: BackupJob): BackupManifest | null {
    const manifest = job.manifest_json
    return (manifest as BackupManifest).kind === 'backup' ? (manifest as BackupManifest) : null
}

export function countMissingMedia(manifest: BackupManifest | null): number {
    return (manifest?.zevs ?? []).reduce((sum, zev) => sum + zev.media.missing.length, 0)
}

export function totalRecords(manifest: BackupManifest | null): number {
    return Object.values(manifest?.counts ?? {}).reduce((sum, n) => sum + n, 0)
}

/** Whether the app can hand the archive to the browser (an S3 object is fetched from the bucket). */
export function isDownloadable(job: BackupJob): boolean {
    return job.status === 'completed' && !!job.archive_location && !job.archive_location.startsWith('s3://')
}
