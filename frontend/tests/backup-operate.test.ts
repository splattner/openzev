import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { BackupSettingsSection } from '../src/features/backups/BackupSettingsSection'
import type { BackupDestination, BackupJob, BackupSchedule, BackupStatus } from '../src/types/api'

// `t` returns the key, so assertions read as "this message is shown".
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const pushToast = vi.fn()
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return {
        ...actual,
        useAppSettings: () => ({
            settings: { date_format_short: 'dd.MM.yyyy', date_format_long: 'd. MMMM yyyy', date_time_format: 'dd.MM.yyyy HH:mm' },
            isLoading: false,
        }),
    }
})

const api = vi.hoisted(() => ({
    fetchBackupStatus: vi.fn(),
    fetchBackupDestinations: vi.fn(),
    fetchBackupJobs: vi.fn(),
    createBackupDestination: vi.fn(),
    updateBackupDestination: vi.fn(),
    deleteBackupDestination: vi.fn(),
    testBackupDestination: vi.fn(),
    createBackupJob: vi.fn(),
    downloadBackupArtifact: vi.fn(),
    fetchRestoreJobs: vi.fn(),
    fetchRestoreJob: vi.fn(),
    createRestoreJob: vi.fn(),
    fetchBackupSchedule: vi.fn(),
    updateBackupSchedule: vi.fn(),
    verifyBackupJob: vi.fn(),
    deleteBackupArtifact: vi.fn(),
}))
vi.mock('../src/lib/api/backups', () => api)
vi.mock('../src/lib/api/zev', () => ({ fetchZevs: vi.fn().mockResolvedValue([]) }))
vi.mock('../src/lib/downloadBlob', () => ({ downloadBlob: vi.fn() }))

const status = (overrides: Partial<BackupStatus> = {}): BackupStatus => ({
    encrypted: true, encryption_key_fingerprint: 'abc123', encryption_key_problem: '', environment_credentials: false,
    destinations_enabled: 1, last_successful: null, last_failed: null, age_hours: null, stale: false,
    schedule_enabled: false, schedule_interval_hours: null, ...overrides,
})

const disk: BackupDestination = {
    id: 'd-disk', name: 'nightly-disk', kind: 'local', enabled: true, path: '/var/backups/openzev', bucket: '', prefix: '',
    region: '', endpoint_url: '', access_key_id: '', server_side_encryption: 'AES256', retention_count: 0,
    credential_mode: 'instance_role', has_secret_access_key: false, created_at: '', updated_at: '',
}

const schedule = (overrides: Partial<BackupSchedule> = {}): BackupSchedule => ({
    enabled: false, frequency: 'daily', hour: 2, minute: 0, day_of_week: 0, timezone: 'Europe/Zurich', interval_hours: 24,
    last_run_at: null, ...overrides,
})

const backup = (overrides: Partial<BackupJob> = {}): BackupJob => ({
    id: 'j-1', scope: 'instance', zev_id: null, zev_name: '', trigger: 'manual', destination_id: 'd-disk',
    destination_name: 'nightly-disk', status: 'completed', created_at: '2026-09-21T04:00:00Z', started_at: '2026-09-21T04:00:00Z',
    completed_at: '2026-09-21T04:01:00Z', archive_name: 'openzev-backup-1.zip', archive_location: '/var/backups/openzev/a.zip',
    archive_bytes: 2048, archive_sha256: 'deadbeef', encrypted: true, encryption_key_fingerprint: 'abc123', manifest_json: {},
    error_message: '', file_expires_at: null, artifact_deleted_at: null, artifact_deleted_reason: '', artifact_available: true,
    verifying: false, verified_at: null, verification_ok: null, verification_message: '', ...overrides,
})

function setup({ statusData = status(), destinations = [disk], jobs = [] as BackupJob[], saved = schedule() } = {}) {
    api.fetchBackupStatus.mockResolvedValue(statusData)
    api.fetchBackupDestinations.mockResolvedValue(destinations)
    api.fetchBackupJobs.mockResolvedValue(jobs)
    api.fetchRestoreJobs.mockResolvedValue([])
    api.fetchBackupSchedule.mockResolvedValue(saved)
}

const cleanups: (() => void)[] = []
afterEach(() => { cleanups.splice(0).forEach((cleanup) => cleanup()); vi.clearAllMocks() })
beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
        writable: true, configurable: true,
        value: (query: string) => ({
            matches: false, media: query, onchange: null, addListener: () => undefined, removeListener: () => undefined,
            addEventListener: () => undefined, removeEventListener: () => undefined, dispatchEvent: () => false,
        }),
    })
})

const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)) })

async function render() {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    await act(async () => root.render(
        createElement(QueryClientProvider, { client },
            createElement(MantineProvider, null, createElement(BackupSettingsSection))),
    ))
    await settle()
    return container
}

function setValue(element: HTMLInputElement | HTMLSelectElement, value: string) {
    const prototype = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value)
    element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
}

const buttons = (container: Element, text: string) =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).filter((b) => b.textContent?.includes(text))
const button = (container: Element, text: string) => buttons(container, text)[0]

async function click(element: Element | undefined | null) {
    expect(element).toBeTruthy()
    await act(async () => { (element as HTMLElement).click() })
    await settle()
}

/** Rows of the job list — the destinations table above it also has `tbody tr`. */
const jobRows = (container: Element) => {
    const card = Array.from(container.querySelectorAll('section.card')).find((c) => c.textContent?.includes('pages.backups.jobs.title'))!
    return card.querySelectorAll('tbody tr')
}

const scheduleCard = (container: Element) =>
    Array.from(container.querySelectorAll('section.card')).find((s) => s.textContent?.includes('pages.backups.schedule.title'))!
const timeInput = (container: Element) => scheduleCard(container).querySelector<HTMLInputElement>('input[type="time"]')!
const saveButton = (container: Element) => button(scheduleCard(container), 'common.save')
const submit = (form: HTMLFormElement) =>
    act(async () => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })

describe('the schedule', () => {
    it('shows what is saved, and Save stays disabled until something changes', async () => {
        setup({ saved: schedule({ enabled: true, hour: 3, minute: 15 }) })
        const container = await render()
        expect(timeInput(container).value).toBe('03:15')
        expect(saveButton(container).disabled).toBe(true)
        await act(async () => setValue(timeInput(container), '04:00'))
        expect(saveButton(container).disabled).toBe(false)
    })

    it('saves the form as the request the API expects, then refreshes the status', async () => {
        setup({ saved: schedule({ enabled: false }) })
        api.updateBackupSchedule.mockResolvedValue(schedule({ enabled: true, hour: 4, minute: 30 }))
        const container = await render()
        await click(scheduleCard(container).querySelector('input[type="checkbox"]'))
        await act(async () => setValue(timeInput(container), '04:30'))
        const before = api.fetchBackupStatus.mock.calls.length
        await submit(scheduleCard(container).querySelector('form')!)
        await settle()
        expect(api.updateBackupSchedule).toHaveBeenCalledWith({ enabled: true, frequency: 'daily', hour: 4, minute: 30, day_of_week: 0 })
        expect(pushToast).toHaveBeenCalledWith('pages.backups.schedule.saved', 'success')
        expect(api.fetchBackupStatus.mock.calls.length).toBeGreaterThan(before)
    })

    it('asks for a weekday only when the schedule is weekly, and sends it', async () => {
        setup()
        api.updateBackupSchedule.mockResolvedValue(schedule({ frequency: 'weekly', day_of_week: 6 }))
        const container = await render()
        const selects = () => Array.from(scheduleCard(container).querySelectorAll('select'))
        expect(selects()).toHaveLength(1)
        await act(async () => setValue(selects()[0], 'weekly'))
        expect(selects()).toHaveLength(2)
        await act(async () => setValue(selects()[1], '6'))
        await submit(scheduleCard(container).querySelector('form')!)
        expect(api.updateBackupSchedule).toHaveBeenCalledWith(expect.objectContaining({ frequency: 'weekly', day_of_week: 6 }))
    })

    it('will not save a time that is not a valid HH:MM', async () => {
        setup()
        const container = await render()
        await act(async () => setValue(timeInput(container), ''))
        expect(saveButton(container).disabled).toBe(true)
        await submit(scheduleCard(container).querySelector('form')!)
        expect(api.updateBackupSchedule).not.toHaveBeenCalled()
    })

    it('says so loudly when an enabled schedule would write unencrypted backups', async () => {
        setup({ saved: schedule({ enabled: true }), statusData: status({ encrypted: false }) })
        const container = await render()
        expect(scheduleCard(container).querySelector('.warning-banner')?.textContent).toContain('pages.backups.schedule.unencrypted')
    })

    it('does not nag about encryption while the schedule is off, or when a key is set', async () => {
        setup({ saved: schedule({ enabled: false }), statusData: status({ encrypted: false }) })
        expect(scheduleCard(await render()).querySelector('.warning-banner')).toBeNull()
        cleanups.splice(0).forEach((cleanup) => cleanup())
        setup({ saved: schedule({ enabled: true }), statusData: status({ encrypted: true }) })
        expect(scheduleCard(await render()).querySelector('.warning-banner')).toBeNull()
    })

    it('warns that a scheduled run has nowhere to write when no destination is enabled', async () => {
        setup({ saved: schedule({ enabled: true }), statusData: status({ destinations_enabled: 0 }) })
        expect(scheduleCard(await render()).textContent).toContain('pages.backups.schedule.noDestination')
    })

    it('shows the server\'s error, and leaves the form as typed', async () => {
        setup()
        api.updateBackupSchedule.mockRejectedValue(new Error('boom'))
        const container = await render()
        await act(async () => setValue(timeInput(container), '05:00'))
        await submit(scheduleCard(container).querySelector('form')!)
        await settle()
        expect(pushToast).toHaveBeenCalledWith(expect.any(String), 'error')
        expect(timeInput(container).value).toBe('05:00')
    })
})

describe('staleness', () => {
    it('is an error banner naming how far behind the schedule is', async () => {
        setup({ statusData: status({ stale: true, age_hours: 73.4, schedule_enabled: true, schedule_interval_hours: 24 }) })
        const container = await render()
        expect(container.querySelector('.error-banner')?.textContent).toContain('pages.backups.status.staleTitle')
        expect(container.querySelector('.error-banner')?.textContent).toContain('pages.backups.status.stale')
    })

    it('says so when a schedule has never produced a backup', async () => {
        setup({ statusData: status({ stale: true, age_hours: null, schedule_enabled: true, schedule_interval_hours: 24 }) })
        expect((await render()).querySelector('.error-banner')?.textContent).toContain('pages.backups.status.staleNever')
    })

    it('is absent when the backups are current', async () => {
        setup()
        expect((await render()).querySelector('.error-banner')).toBeNull()
    })
})

describe('checking and deleting a backup\'s file', () => {
    it('offers Check, Download and Delete file for a finished backup that still has its file', async () => {
        setup({ jobs: [backup()] })
        const container = await render()
        for (const key of ['pages.backups.jobs.check', 'pages.backups.jobs.download', 'pages.backups.jobs.deleteFile']) {
            expect(button(container, key), key).toBeTruthy()
        }
    })

    it('queues a check and refreshes the list', async () => {
        setup({ jobs: [backup()] })
        api.verifyBackupJob.mockResolvedValue(backup({ verifying: true }))
        const container = await render()
        const before = api.fetchBackupJobs.mock.calls.length
        await click(button(container, 'pages.backups.jobs.check'))
        expect(api.verifyBackupJob).toHaveBeenCalledWith('j-1')
        expect(api.fetchBackupJobs.mock.calls.length).toBeGreaterThan(before)
    })

    it('cannot start a second check while one is running, and says it is checking', async () => {
        setup({ jobs: [backup({ verifying: true })] })
        const container = await render()
        expect(button(container, 'pages.backups.jobs.check').disabled).toBe(true)
        expect(container.textContent).toContain('pages.backups.jobs.verification.checking')
    })

    it('shows the result of the last check, and why a failed one failed', async () => {
        setup({ jobs: [
            backup({ id: 'ok', verification_ok: true, verified_at: '2026-09-21T05:00:00Z' }),
            backup({ id: 'bad', verification_ok: false, verified_at: '2026-09-21T05:00:00Z', verification_message: 'The stored file does not match the checksum recorded when it was written.' }),
            backup({ id: 'new' }),
        ] })
        const container = await render()
        const rows = jobRows(container)
        expect(rows[0].textContent).toContain('pages.backups.jobs.verification.ok')
        expect(rows[1].textContent).toContain('pages.backups.jobs.verification.failed')
        expect(rows[1].textContent).toContain('does not match the checksum')
        expect(rows[2].textContent).toContain('pages.backups.jobs.verification.never')
    })

    it('asks before deleting a file, and does nothing if the answer is no', async () => {
        setup({ jobs: [backup()] })
        const container = await render()
        await click(button(container, 'pages.backups.jobs.deleteFile'))
        expect(container.textContent).toContain('pages.backups.jobs.deleteFileTitle')
        expect(api.deleteBackupArtifact).not.toHaveBeenCalled()
        await click(button(container, 'common.cancel'))
        expect(api.deleteBackupArtifact).not.toHaveBeenCalled()
        expect(container.textContent).not.toContain('pages.backups.jobs.deleteFileTitle')
    })

    it('deletes the file once confirmed', async () => {
        setup({ jobs: [backup()] })
        api.deleteBackupArtifact.mockResolvedValue(undefined)
        const container = await render()
        await click(button(container, 'pages.backups.jobs.deleteFile'))
        const dialogConfirm = buttons(container, 'pages.backups.jobs.deleteFile').at(-1)
        await click(dialogConfirm)
        expect(api.deleteBackupArtifact).toHaveBeenCalledWith('j-1')
    })

    it('leaves a deleted backup as history: no actions, and it says why the file went', async () => {
        setup({ jobs: [backup({ artifact_available: false, artifact_deleted_at: '2026-09-22T00:00:00Z', artifact_deleted_reason: 'retention' })] })
        const container = await render()
        const row = jobRows(container)[0]
        expect(row.textContent).toContain('pages.backups.jobs.fileGone.retention')
        for (const key of ['pages.backups.jobs.check', 'pages.backups.jobs.download', 'pages.backups.jobs.deleteFile']) {
            expect(row.textContent, key).not.toContain(key)
        }
        expect(row.textContent).not.toContain('pages.backups.jobs.verification')
    })

    it('shows when a safety backup will expire, and marks scheduled and safety backups', async () => {
        setup({ jobs: [
            backup({ id: 'safe', trigger: 'pre_restore', file_expires_at: '2026-10-21T00:00:00Z' }),
            backup({ id: 'sched', trigger: 'scheduled' }),
            backup({ id: 'hand', trigger: 'manual' }),
        ] })
        const rows = jobRows(await render())
        expect(rows[0].textContent).toContain('pages.backups.jobs.trigger.pre_restore')
        expect(rows[0].textContent).toContain('pages.backups.jobs.expires')
        expect(rows[1].textContent).toContain('pages.backups.jobs.trigger.scheduled')
        expect(rows[2].textContent).not.toContain('pages.backups.jobs.trigger')
    })

    it('does not offer a deleted backup as something to restore from', async () => {
        setup({ jobs: [backup({ artifact_available: false, artifact_deleted_at: '2026-09-22T00:00:00Z' })] })
        // The restore section reads the same list and finds nothing usable in it.
        expect((await render()).textContent).toContain('pages.backups.restore.noBackups')
    })
})

describe('retention on a destination', () => {
    it('is listed: everything, or the latest N', async () => {
        setup({ destinations: [disk, { ...disk, id: 'd-2', name: 'offsite', retention_count: 7 }] })
        const text = Array.from((await render()).querySelectorAll('tbody tr')).map((r) => r.textContent).join('|')
        expect(text).toContain('pages.backups.destinations.keepsAll')
        expect(text).toContain('pages.backups.destinations.keepsN')
    })

    it('is sent with a new destination, and zero means keep everything', async () => {
        setup({ destinations: [] })
        api.createBackupDestination.mockResolvedValue(disk)
        const container = await render()
        await click(button(container, 'pages.backups.destinations.add'))
        const label = (key: string) => Array.from(container.querySelectorAll('label')).find((l) => l.textContent?.includes(key))!
        await act(async () => setValue(label('pages.backups.form.name').querySelector('input')!, 'weekly'))
        await act(async () => setValue(label('pages.backups.form.path').querySelector('input')!, '/mnt/backups'))
        await act(async () => setValue(label('pages.backups.form.retention').querySelector('input')!, '5'))
        await submit(container.querySelector('form[class*="page-stack"], form')! as HTMLFormElement)
        expect(api.createBackupDestination.mock.calls[0][0].retention_count).toBe(5)
    })
})
