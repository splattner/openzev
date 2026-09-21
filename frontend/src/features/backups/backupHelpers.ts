import type {
    BackupDestination,
    BackupDestinationInput,
    BackupDestinationKind,
    BackupJob,
    BackupManifest,
    BackupSchedule,
    BackupScheduleInput,
    RestoreConflict,
    RestoreJob,
    RestorePlan,
} from '../../types/api'

/** While a job runs, or a check of its file does, its row is still changing, so the list keeps polling. */
export function hasActiveJob(jobs: BackupJob[] | undefined): boolean {
    return (jobs ?? []).some((job) => job.status === 'queued' || job.status === 'running' || job.verifying)
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
    /** Typed as text so an empty box is not silently `0`; blank and `0` both keep everything. */
    retention_count: string
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
    retention_count: '0',
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
        retention_count: String(destination.retention_count),
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
    const base = {
        name: form.name.trim(),
        kind: form.kind,
        enabled: form.enabled,
        retention_count: parseRetention(form.retention_count),
    }

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

/** A retention box's text as the count the API takes: whole, non-negative, blank meaning "keep everything". */
export function parseRetention(text: string): number {
    const n = Number.parseInt(text.trim(), 10)
    return Number.isFinite(n) && n > 0 ? n : 0
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
    return job.artifact_available && !!job.archive_location && !job.archive_location.startsWith('s3://')
}

/** What the last check of a backup's file found, for the badge next to it. */
export type VerificationState = 'checking' | 'ok' | 'failed' | 'never'

export function verificationState(job: BackupJob): VerificationState {
    if (job.verifying) return 'checking'
    if (job.verification_ok === true) return 'ok'
    if (job.verification_ok === false) return 'failed'
    return 'never'
}

/** Whether "check" and "delete file" apply: a finished backup whose file is still there. */
export function hasFile(job: BackupJob): boolean {
    return job.artifact_available
}

/** A backup that has no file left is history, not something to restore from. */
export function fileGone(job: BackupJob): boolean {
    return job.status === 'completed' && !job.artifact_available
}

// ── restoring one community ──────────────────────────────────────────────────

/** Backups a community can be restored from: finished, and holding at least one community. */
export function restorableBackups(jobs: BackupJob[] | undefined): BackupJob[] {
    return (jobs ?? []).filter(
        (job) => job.artifact_available && (readManifest(job)?.zevs.length ?? 0) > 0,
    )
}

/** The communities a backup holds, by id and name. */
export function communitiesIn(job: BackupJob | undefined): { id: string; name: string }[] {
    const manifest = job ? readManifest(job) : null
    return (manifest?.zevs ?? []).map((zev) => ({ id: zev.id, name: zev.name }))
}

/** The plan a job carries, or `null` while it has none (queued, running, or failed before planning). */
export function readPlan(job: RestoreJob | null | undefined): RestorePlan | null {
    const plan = job?.plan_json as Partial<RestorePlan> | undefined
    return plan && plan.zev && plan.sections && plan.conflicts ? (plan as RestorePlan) : null
}

export function hasActiveRestore(jobs: RestoreJob[] | undefined): boolean {
    return (jobs ?? []).some((job) => job.status === 'queued' || job.status === 'running')
}

/** Problems no `force` can get past: they would damage something else. */
export function hardConflicts(plan: RestorePlan): RestoreConflict[] {
    return plan.conflicts.filter((c) => !c.overridable)
}

/** Problems that need the administrator to say so: issued invoices or contracts would be lost or rolled back. */
export function forceableConflicts(plan: RestorePlan): RestoreConflict[] {
    return plan.conflicts.filter((c) => c.overridable)
}

/**
 * Whether a real restore may be started from a finished preview.
 *
 * A hard conflict always blocks. A forceable one blocks until `force` is ticked,
 * so the choice to lose an issued invoice is a separate, deliberate act.
 */
export function canStartRestore(plan: RestorePlan, force: boolean): boolean {
    if (hardConflicts(plan).length > 0) return false
    return forceableConflicts(plan).length === 0 || force
}

/**
 * What the administrator has to type to confirm. The community's current name if
 * it exists (the thing being overwritten), else the backup's name for it.
 */
export function confirmationName(plan: RestorePlan): string {
    return plan.zev.exists_now && plan.zev.current_name ? plan.zev.current_name : plan.zev.name
}

/** Section names in the order the backend restores them, so a table reads top-down as a dependency chain. */
export const RESTORE_SECTION_ORDER = [
    'zev',
    'participants',
    'metering_points',
    'tariffs',
    'readings',
    'import_logs',
    'invoices',
    'contract_issues',
    'audit_events',
] as const

// ── the schedule ─────────────────────────────────────────────────────────────

export interface ScheduleFormState {
    enabled: boolean
    frequency: 'daily' | 'weekly'
    /** `HH:MM`, as an `<input type="time">` holds it. */
    time: string
    day_of_week: number
}

const pad = (n: number) => String(n).padStart(2, '0')

export function scheduleToForm(schedule: BackupSchedule): ScheduleFormState {
    return {
        enabled: schedule.enabled,
        frequency: schedule.frequency,
        time: `${pad(schedule.hour)}:${pad(schedule.minute)}`,
        day_of_week: schedule.day_of_week,
    }
}

/** The request for a schedule form, or `null` while its time is not a valid `HH:MM`. */
export function buildSchedulePayload(form: ScheduleFormState): BackupScheduleInput | null {
    const match = /^(\d{1,2}):(\d{2})$/.exec(form.time)
    if (!match) return null
    const hour = Number(match[1])
    const minute = Number(match[2])
    if (hour > 23 || minute > 59) return null
    return {
        enabled: form.enabled,
        frequency: form.frequency,
        hour,
        minute,
        // Only meaningful (and only sent as such) for a weekly schedule.
        day_of_week: form.frequency === 'weekly' ? form.day_of_week : 0,
    }
}

/** Cron weekday numbers in the order a week is listed, Sunday first as cron numbers them. */
export const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6] as const

/** Whether a form differs from what is saved, so Save can stay disabled until it matters. */
export function scheduleChanged(form: ScheduleFormState, saved: BackupSchedule): boolean {
    const now = scheduleToForm(saved)
    return (
        form.enabled !== now.enabled ||
        form.frequency !== now.frequency ||
        form.time !== now.time ||
        (form.frequency === 'weekly' && form.day_of_week !== now.day_of_week)
    )
}
