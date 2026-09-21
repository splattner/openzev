import { describe, expect, it } from 'vitest'
import {
    EMPTY_DESTINATION_FORM,
    buildDestinationPayload,
    buildSchedulePayload,
    destinationToForm,
    fileGone,
    hasActiveJob,
    parseRetention,
    scheduleChanged,
    scheduleToForm,
    verificationState,
} from '../src/features/backups/backupHelpers'
import type { BackupDestination, BackupJob, BackupSchedule } from '../src/types/api'

const schedule = (overrides: Partial<BackupSchedule> = {}): BackupSchedule => ({
    enabled: true, frequency: 'daily', hour: 2, minute: 5, day_of_week: 0, timezone: 'Europe/Zurich', interval_hours: 24,
    last_run_at: null, ...overrides,
})

const job = (overrides: Partial<BackupJob> = {}): BackupJob => ({
    id: 'j1', scope: 'instance', zev_id: null, zev_name: '', trigger: 'manual', destination_id: 'd1', destination_name: 'disk',
    status: 'completed', created_at: '', started_at: null, completed_at: null, archive_name: 'a.zip', archive_location: '/x/a.zip',
    archive_bytes: 1, archive_sha256: '', encrypted: false, encryption_key_fingerprint: '', manifest_json: {}, error_message: '',
    file_expires_at: null, artifact_deleted_at: null, artifact_deleted_reason: '', artifact_available: true, verifying: false,
    verified_at: null, verification_ok: null, verification_message: '', ...overrides,
})

describe('the schedule form', () => {
    it('shows the saved time as HH:MM with leading zeros', () => {
        expect(scheduleToForm(schedule({ hour: 2, minute: 5 })).time).toBe('02:05')
        expect(scheduleToForm(schedule({ hour: 23, minute: 59 })).time).toBe('23:59')
    })

    it('builds the request from the form', () => {
        expect(buildSchedulePayload({ enabled: true, frequency: 'daily', time: '03:30', day_of_week: 4 })).toEqual({
            enabled: true, frequency: 'daily', hour: 3, minute: 30, day_of_week: 0,
        })
    })

    it('sends the weekday only for a weekly schedule', () => {
        expect(buildSchedulePayload({ enabled: true, frequency: 'weekly', time: '03:30', day_of_week: 4 })?.day_of_week).toBe(4)
        expect(buildSchedulePayload({ enabled: true, frequency: 'daily', time: '03:30', day_of_week: 4 })?.day_of_week).toBe(0)
    })

    it('refuses a time that is not a valid HH:MM instead of sending it', () => {
        for (const time of ['', '25:00', '12:60', 'noon', '1:5']) {
            expect(buildSchedulePayload({ enabled: true, frequency: 'daily', time, day_of_week: 0 }), time).toBeNull()
        }
    })

    it('reports a change only when something the server stores differs', () => {
        const saved = schedule({ frequency: 'daily', day_of_week: 0 })
        const form = scheduleToForm(saved)
        expect(scheduleChanged(form, saved)).toBe(false)
        expect(scheduleChanged({ ...form, enabled: false }, saved)).toBe(true)
        expect(scheduleChanged({ ...form, time: '04:00' }, saved)).toBe(true)
        // A weekday that a daily schedule ignores is not a change.
        expect(scheduleChanged({ ...form, day_of_week: 3 }, saved)).toBe(false)
        expect(scheduleChanged({ ...form, frequency: 'weekly', day_of_week: 3 }, saved)).toBe(true)
    })
})

describe('retention in the destination form', () => {
    it('reads blank, zero, negative and junk as "keep everything"', () => {
        for (const text of ['', ' ', '0', '-3', 'abc']) expect(parseRetention(text), text).toBe(0)
    })

    it('reads a whole number', () => {
        expect(parseRetention('7')).toBe(7)
        expect(parseRetention(' 12 ')).toBe(12)
        expect(parseRetention('3.9')).toBe(3)
    })

    it('is sent with every destination, local or S3', () => {
        expect(buildDestinationPayload({ ...EMPTY_DESTINATION_FORM, name: 'a', path: '/b', retention_count: '5' }).retention_count).toBe(5)
        expect(buildDestinationPayload({ ...EMPTY_DESTINATION_FORM, kind: 's3', bucket: 'x', retention_count: '2' }).retention_count).toBe(2)
    })

    it('is shown as typed when editing, so the box reads what is saved', () => {
        const destination = { ...EMPTY_DESTINATION_FORM, retention_count: 0 } as unknown as BackupDestination
        expect(destinationToForm({ ...destination, retention_count: 9 } as BackupDestination).retention_count).toBe('9')
    })
})

describe('what a backup\'s file and check look like', () => {
    it('tells the four verification states apart', () => {
        expect(verificationState(job())).toBe('never')
        expect(verificationState(job({ verification_ok: true }))).toBe('ok')
        expect(verificationState(job({ verification_ok: false }))).toBe('failed')
        expect(verificationState(job({ verifying: true, verification_ok: true }))).toBe('checking')
    })

    it('calls a finished backup without a file gone, but not a failed one', () => {
        expect(fileGone(job({ artifact_available: false, artifact_deleted_at: '2026-09-22T00:00:00Z' }))).toBe(true)
        expect(fileGone(job())).toBe(false)
        expect(fileGone(job({ status: 'failed', artifact_available: false }))).toBe(false)
    })

    it('keeps polling while a check runs, not only while a backup does', () => {
        expect(hasActiveJob([job({ verifying: true })])).toBe(true)
        expect(hasActiveJob([job()])).toBe(false)
    })
})
