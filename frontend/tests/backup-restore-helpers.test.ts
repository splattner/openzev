import { describe, expect, it } from 'vitest'
import {
    canStartRestore,
    communitiesIn,
    confirmationName,
    forceableConflicts,
    hardConflicts,
    hasActiveRestore,
    readPlan,
    restorableBackups,
} from '../src/features/backups/backupHelpers'
import type { BackupJob, RestoreConflict, RestoreJob, RestorePlan } from '../src/types/api'

const plan = (overrides: Partial<RestorePlan> = {}): RestorePlan => ({
    zev: { id: 'z1', name: 'Sonnenhof', exists_now: true, current_name: 'Sonnenhof (renamed)' },
    backup: { created_at: '2026-09-21T04:00:00+02:00', scope: 'instance', instance_name: '', openzev_version: '1.0.0' },
    sections: { zev: { backup: 1, current: 1, kept: false }, audit_events: { backup: 5, current: 9, kept: true } },
    accounts: { relink: 3, missing: [] },
    media: { files: 2, missing: 0 },
    conflicts: [],
    blocked: false,
    safety_backup_id: null,
    restored: null,
    ...overrides,
})

const soft: RestoreConflict = { kind: 'sent_invoice_deleted', detail: 'INV-1 (paid)', overridable: true }
const hard: RestoreConflict = { kind: 'export_in_progress', detail: 'running', overridable: false }

const backup = (overrides: Partial<BackupJob> = {}): BackupJob => ({
    id: 'b1', scope: 'instance', zev_id: null, zev_name: '', trigger: 'manual', destination_id: 'd1', destination_name: 'disk',
    status: 'completed', created_at: '', started_at: null, completed_at: null, archive_name: '', archive_location: '',
    archive_bytes: null, archive_sha256: '', encrypted: false, encryption_key_fingerprint: '', error_message: '',
    artifact_available: true, file_expires_at: null, artifact_deleted_at: null, artifact_deleted_reason: '', verifying: false, verified_at: null, verification_ok: null, verification_message: '',
    manifest_json: {
        kind: 'backup', format_version: 1, created_at: '', instance_name: '', openzev_version: '', scope: 'instance', zev_id: null,
        migrations: {}, counts: {}, members: {}, encryption: null, secret_fingerprints: {},
        zevs: [
            { id: 'z1', name: 'Sonnenhof', counts: {}, media: { files: 0, bytes: 0, missing: [], unsafe: [] } },
            { id: 'z2', name: 'Bergblick', counts: {}, media: { files: 0, bytes: 0, missing: [], unsafe: [] } },
        ],
    } as unknown as BackupJob['manifest_json'],
    ...overrides,
})

const restoreJob = (overrides: Partial<RestoreJob> = {}): RestoreJob => ({
    id: 'r1', target_zev_id: 'z1', target_zev_name: 'Sonnenhof', source_backup_id: 'b1', source_archive_name: '',
    source_created_at: null, source_description: '', dry_run: true, force: false, status: 'completed', plan_json: {},
    safety_backup_id: null, created_at: '', started_at: null, completed_at: null, error_message: '', ...overrides,
})

describe('starting a restore from a finished preview', () => {
    it('is allowed when nothing stands in the way', () => {
        expect(canStartRestore(plan(), false)).toBe(true)
    })

    it('needs the switch for an issued invoice or contract that would be lost', () => {
        expect(canStartRestore(plan({ conflicts: [soft] }), false)).toBe(false)
        expect(canStartRestore(plan({ conflicts: [soft] }), true)).toBe(true)
    })

    it('can never be forced past a problem that would damage something else', () => {
        expect(canStartRestore(plan({ conflicts: [hard] }), true)).toBe(false)
        expect(canStartRestore(plan({ conflicts: [soft, hard] }), true)).toBe(false)
    })

    it('splits conflicts by whether force can help', () => {
        const both = plan({ conflicts: [soft, hard] })
        expect(forceableConflicts(both)).toEqual([soft])
        expect(hardConflicts(both)).toEqual([hard])
    })
})

describe('the name to type before a restore', () => {
    it('is the name the community has now: that is what gets overwritten', () => {
        expect(confirmationName(plan())).toBe('Sonnenhof (renamed)')
    })

    it('is the backup\'s name when the community has been deleted', () => {
        expect(confirmationName(plan({ zev: { id: 'z1', name: 'Sonnenhof', exists_now: false, current_name: '' } }))).toBe('Sonnenhof')
    })
})

describe('reading a job\'s plan', () => {
    it('returns the plan once the job has one', () => {
        expect(readPlan(restoreJob({ plan_json: plan() }))?.zev.name).toBe('Sonnenhof')
    })

    it('returns null while there is none, and for a damaged-archive report', () => {
        expect(readPlan(restoreJob())).toBeNull()
        expect(readPlan(restoreJob({ plan_json: { verification_failures: ['x'] } }))).toBeNull()
        expect(readPlan(undefined)).toBeNull()
    })
})

describe('choosing what to restore from', () => {
    it('offers finished backups that hold a community, and lists the communities', () => {
        const failed = backup({ id: 'b2', status: 'failed', artifact_available: false })
        const deleted = backup({ id: 'b4', artifact_available: false, artifact_deleted_at: '2026-09-22T00:00:00Z' })
        const empty = backup({ id: 'b3', manifest_json: {} })
        expect(restorableBackups([backup(), failed, empty, deleted]).map((j) => j.id)).toEqual(['b1'])
        expect(communitiesIn(backup())).toEqual([{ id: 'z1', name: 'Sonnenhof' }, { id: 'z2', name: 'Bergblick' }])
        expect(communitiesIn(undefined)).toEqual([])
        expect(restorableBackups(undefined)).toEqual([])
    })
})

describe('polling', () => {
    it('continues while a restore is queued or running', () => {
        expect(hasActiveRestore([restoreJob({ status: 'running' })])).toBe(true)
        expect(hasActiveRestore([restoreJob({ status: 'queued' })])).toBe(true)
        expect(hasActiveRestore([restoreJob()])).toBe(false)
        expect(hasActiveRestore(undefined)).toBe(false)
    })
})
