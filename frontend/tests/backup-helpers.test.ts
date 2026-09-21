import { describe, expect, it } from 'vitest'
import {
    EMPTY_DESTINATION_FORM,
    buildDestinationPayload,
    countMissingMedia,
    destinationTarget,
    destinationToForm,
    hasActiveJob,
    isDownloadable,
    readManifest,
    totalRecords,
    type DestinationFormState,
} from '../src/features/backups/backupHelpers'
import type { BackupDestination, BackupJob, BackupManifest } from '../src/types/api'

const s3Destination: BackupDestination = {
    id: 'd1', name: 'cloud', kind: 's3', enabled: true, path: '', bucket: 'openzev', prefix: 'prod/',
    region: 'eu-central-1', endpoint_url: 'https://minio.internal:9000', access_key_id: 'AKIA',
    server_side_encryption: 'AES256', retention_count: 0, credential_mode: 'stored', has_secret_access_key: true,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const s3Form = (overrides: Partial<DestinationFormState> = {}): DestinationFormState => ({
    ...destinationToForm(s3Destination),
    ...overrides,
})

const manifest: BackupManifest = {
    kind: 'backup', format_version: 1, created_at: '2026-09-21T04:00:00+02:00', instance_name: '', openzev_version: '',
    scope: 'instance', zev_id: null, encryption: null,
    counts: { 'instance/accounts': 3, 'zevs/a/readings': 100 },
    zevs: [
        { id: 'a', name: 'Alpha', counts: {}, media: { files: 2, bytes: 10, missing: ['x.pdf'], unsafe: [] } },
        { id: 'b', name: 'Beta', counts: {}, media: { files: 1, bytes: 5, missing: ['y.pdf', 'z.pdf'], unsafe: [] } },
    ],
}

const job = (overrides: Partial<BackupJob> = {}): BackupJob => ({
    id: 'j1', scope: 'instance', zev_id: null, zev_name: '', trigger: 'manual', destination_id: 'd1',
    destination_name: 'disk', status: 'completed', created_at: '2026-09-21T04:00:00Z', started_at: null,
    completed_at: null, archive_name: 'a.zip', archive_location: '/backups/a.zip', archive_bytes: 10,
    archive_sha256: 'abc', encrypted: false, encryption_key_fingerprint: '', manifest_json: {}, error_message: '',
    file_expires_at: null, artifact_deleted_at: null, artifact_deleted_reason: '', artifact_available: true, verifying: false,
    verified_at: null, verification_ok: null, verification_message: '',
    ...overrides,
})

describe('buildDestinationPayload', () => {
    it('sends a local destination with every S3 field empty', () => {
        const payload = buildDestinationPayload({ ...EMPTY_DESTINATION_FORM, name: ' nightly ', path: ' /var/backups ' })
        expect(payload).toMatchObject({ name: 'nightly', kind: 'local', path: '/var/backups', bucket: '', prefix: '', region: '', endpoint_url: '', access_key_id: '' })
        expect(payload).not.toHaveProperty('secret_access_key')
    })

    it('leaves a stored secret alone when the field is untouched — a blank edit must never wipe a credential', () => {
        const payload = buildDestinationPayload(s3Form(), s3Destination)
        expect(payload).not.toHaveProperty('secret_access_key')
    })

    it('sends a new secret when one is typed', () => {
        expect(buildDestinationPayload(s3Form({ secret_access_key: 'new-secret' }), s3Destination).secret_access_key).toBe('new-secret')
    })

    it('clears the secret only on explicit request', () => {
        expect(buildDestinationPayload(s3Form({ remove_secret: true }), s3Destination).secret_access_key).toBe('')
    })

    it('a typed secret wins over a stale remove flag', () => {
        const payload = buildDestinationPayload(s3Form({ secret_access_key: 'typed', remove_secret: true }), s3Destination)
        expect(payload.secret_access_key).toBe('typed')
    })

    it('switching an S3 destination to local clears the stored secret and the S3 fields', () => {
        const payload = buildDestinationPayload(s3Form({ kind: 'local', path: '/backups' }), s3Destination)
        expect(payload.secret_access_key).toBe('')
        expect(payload).toMatchObject({ kind: 'local', path: '/backups', bucket: '', endpoint_url: '', access_key_id: '' })
    })

    it('does not send a clearing secret for a local destination that never had one', () => {
        const local = { ...s3Destination, kind: 'local' as const, has_secret_access_key: false }
        expect(buildDestinationPayload({ ...EMPTY_DESTINATION_FORM, path: '/b' }, local)).not.toHaveProperty('secret_access_key')
    })

    it('strips leading slashes from the prefix, which the server rejects, and trims fields', () => {
        const payload = buildDestinationPayload(s3Form({ prefix: '  //nightly/  ', bucket: ' b ', region: ' r ' }))
        expect(payload).toMatchObject({ prefix: 'nightly/', bucket: 'b', region: 'r', path: '' })
    })

    it('an S3 destination with no credentials at all is valid: it means an instance role', () => {
        const payload = buildDestinationPayload(s3Form({ access_key_id: '', secret_access_key: '', remove_secret: false }))
        expect(payload).toMatchObject({ access_key_id: '' })
        expect(payload).not.toHaveProperty('secret_access_key')
    })
})

describe('destinationToForm', () => {
    it('never pre-fills the secret, because the server never returns it', () => {
        const form = destinationToForm(s3Destination)
        expect(form.secret_access_key).toBe('')
        expect(form.remove_secret).toBe(false)
    })
})

describe('destinationTarget', () => {
    it('is the directory for a local destination', () => {
        expect(destinationTarget({ ...s3Destination, kind: 'local', path: '/var/backups' })).toBe('/var/backups')
    })
    it('is bucket/prefix at the endpoint for S3', () => {
        expect(destinationTarget(s3Destination)).toBe('openzev/prod @ https://minio.internal:9000')
    })
    it('omits the endpoint for plain AWS and copes with no prefix', () => {
        expect(destinationTarget({ ...s3Destination, endpoint_url: '', prefix: '' })).toBe('openzev')
    })
})

describe('job helpers', () => {
    it('polls only while something is queued or running', () => {
        expect(hasActiveJob(undefined)).toBe(false)
        expect(hasActiveJob([job(), job({ status: 'failed' })])).toBe(false)
        expect(hasActiveJob([job(), job({ status: 'queued' })])).toBe(true)
        expect(hasActiveJob([job({ status: 'running' })])).toBe(true)
    })

    it('reads a manifest only once the job has produced one', () => {
        expect(readManifest(job({ manifest_json: {} }))).toBeNull()
        expect(readManifest(job({ manifest_json: manifest }))).toBe(manifest)
    })

    it('sums missing PDFs and records across the manifest', () => {
        expect(countMissingMedia(manifest)).toBe(3)
        expect(countMissingMedia(null)).toBe(0)
        expect(totalRecords(manifest)).toBe(103)
        expect(totalRecords(null)).toBe(0)
    })

    it('offers a download only for a finished local archive — S3 objects are fetched from the bucket', () => {
        expect(isDownloadable(job())).toBe(true)
        expect(isDownloadable(job({ archive_location: 's3://b/a.zip' }))).toBe(false)
        expect(isDownloadable(job({ status: 'running', archive_location: '', artifact_available: false }))).toBe(false)
        expect(isDownloadable(job({ status: 'failed', artifact_available: false }))).toBe(false)
        // The row outlives its file: a deleted backup has nothing to download.
        expect(isDownloadable(job({ artifact_available: false, artifact_deleted_at: '2026-09-22T00:00:00Z' }))).toBe(false)
    })
})
