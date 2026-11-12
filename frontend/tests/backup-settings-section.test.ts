import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter } from 'react-router-dom'
import { waitForCondition } from './helpers/waitForCondition'
import { queryKeys } from '../src/lib/api/queryKeys'
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
vi.mock('../src/lib/api/zev', () => ({
    fetchZevs: vi.fn().mockResolvedValue([{ id: 'zev-1', name: 'Sonnenhof' }, { id: 'zev-2', name: 'Bergblick' }]),
}))
const downloadBlob = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/downloadBlob', () => ({ downloadBlob }))

const status = (overrides: Partial<BackupStatus> = {}): BackupStatus => ({
    encrypted: true, encryption_required: false, encryption_key_fingerprint: 'abc123', encryption_key_problem: '', environment_credentials: false,
    destinations_enabled: 1, last_successful: null, last_failed: null, age_hours: null, stale: false,
    schedule_enabled: false, schedule_interval_hours: null, ...overrides,
})

const disk: BackupDestination = {
    id: 'd-disk', name: 'nightly-disk', kind: 'local', enabled: true, path: '/var/backups/openzev', bucket: '', prefix: '',
    region: '', endpoint_url: '', access_key_id: '', server_side_encryption: 'AES256', retention_count: 0, credential_mode: 'instance_role',
    has_secret_access_key: false, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const completed = (overrides: Partial<BackupJob> = {}): BackupJob => ({
    id: 'j-1', scope: 'instance', zev_id: null, zev_name: '', trigger: 'manual', destination_id: 'd-disk',
    destination_name: 'nightly-disk', status: 'completed', created_at: '2026-09-21T04:00:00Z',
    started_at: '2026-09-21T04:00:00Z', completed_at: '2026-09-21T04:01:00Z', archive_name: 'openzev-backup-1.zip',
    archive_location: '/var/backups/openzev/openzev-backup-1.zip', archive_bytes: 2048, archive_sha256: 'deadbeef',
    encrypted: true, encryption_key_fingerprint: 'abc123', manifest_json: {}, error_message: '',
    artifact_available: true, file_expires_at: null, artifact_deleted_at: null, artifact_deleted_reason: '', verifying: false, verified_at: null, verification_ok: null, verification_message: '', ...overrides,
})

const schedule = (overrides: Partial<BackupSchedule> = {}): BackupSchedule => ({
    enabled: false, frequency: 'daily', hour: 2, minute: 0, day_of_week: 0, timezone: 'Europe/Zurich', interval_hours: 24,
    last_run_at: null, ...overrides,
})

function setup({ statusData = status(), destinations = [disk], jobs = [] as BackupJob[] } = {}) {
    api.fetchBackupStatus.mockResolvedValue(statusData)
    api.fetchBackupDestinations.mockResolvedValue(destinations)
    api.fetchBackupJobs.mockResolvedValue(jobs)
    api.fetchRestoreJobs.mockResolvedValue([])
    api.fetchBackupSchedule.mockResolvedValue(schedule())
}

const cleanups: (() => void)[] = []
const clients = new WeakMap<Element, QueryClient>()
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

async function render(waitForQueries = true) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    clients.set(container, client)
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    await act(async () => root.render(
        createElement(QueryClientProvider, { client },
            createElement(MemoryRouter, null, createElement(MantineProvider, null, createElement(BackupSettingsSection)))),
    ))
    // Query caches can settle before React receives their notifications.
    if (waitForQueries) await waitForCondition(() => client.isFetching() === 0
        && !container.querySelector('.skeleton-block')
        && !container.textContent?.includes('common.loading'), 'backup content', 5000)
    return container
}

function setValue(element: HTMLInputElement | HTMLSelectElement, value: string) {
    const prototype = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(element, value)
    element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
}

const button = (container: Element, text: string) =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((b) => b.textContent?.includes(text))

async function click(element: Element | undefined | null) {
    expect(element).toBeTruthy()
    await act(async () => { (element as HTMLElement).click() })
}

const labelled = (container: Element, key: string) =>
    Array.from(container.querySelectorAll('label')).find((l) => l.textContent?.includes(key))

it.each([
    ['destination', 'testBackupDestination', 'common.edit', 'pages.backups.destinations.test'],
    ['job', 'verifyBackupJob', 'pages.backups.jobs.details', 'pages.backups.jobs.check'],
] as const)('keeps %s action focus while another action is pending', async (_kind, operation, focusLabel, triggerLabel) => {
    setup({ jobs: [completed()] })
    let finish!: () => void
    api[operation].mockReturnValueOnce(new Promise<void>((resolve) => { finish = resolve }))
    const container = await render()
    const focused = button(container, focusLabel)!
    focused.focus()
    const trigger = button(container, triggerLabel)!
    await click(trigger)
    await waitForCondition(() => trigger.disabled, 'pending action')
    expect(document.activeElement).toBe(focused)
    await act(async () => { finish() })
    await waitForCondition(() => !trigger.disabled, 'completed action')
    expect(document.activeElement).toBe(focused)
})

it('sorts backup start times chronologically across the daylight-saving fallback', async () => {
    setup({ jobs: [
        completed({ id: 'older', destination_name: 'older', started_at: '2026-10-25T02:30:00+02:00', created_at: '2026-10-25T03:30:00+01:00' }),
        completed({ id: 'newer', destination_name: 'newer', started_at: null, created_at: '2026-10-25T02:10:00+01:00' }),
    ] })
    const container = await render()
    const heading = button(container, 'pages.backups.jobs.columns.created')!
    const table = heading.closest('table')!
    const destinations = () => Array.from(table.querySelectorAll('tbody tr'), (row) => row.children[2].textContent)
    expect(destinations()).toEqual(['newer', 'older'])
    await click(heading)
    expect(destinations()).toEqual(['older', 'newer'])
})

it('sorts backup statuses and integrity by priority on the first click', async () => {
    setup({ jobs: [
        completed({ id: 'ok', verification_ok: true }),
        completed({ id: 'queued', status: 'queued', artifact_available: false }),
        completed({ id: 'running', status: 'running', artifact_available: false }),
        completed({ id: 'checking', verifying: true }),
        completed({ id: 'never' }),
        completed({ id: 'bad-file', verification_ok: false }),
        completed({ id: 'removed', artifact_available: false }),
        completed({ id: 'failed', status: 'failed', artifact_available: false }),
    ] })
    const container = await render()
    const heading = button(container, 'pages.backups.jobs.columns.status')!
    const table = heading.closest('table')!
    await click(heading)
    const cells = (index: number) => Array.from(table.querySelectorAll('tbody tr'), (row) =>
        row.children[index].querySelector('.badge')?.textContent ?? row.children[index].textContent)
    expect(cells(3)).toEqual(['failed', 'queued', 'running', ...Array(5).fill('completed')]
        .map((status) => `pages.backups.jobs.status.${status}`))
    await click(button(container, 'pages.backups.jobs.columns.integrity'))
    expect(cells(6)).toEqual(['failed', 'checking', 'never', 'ok', '—', '—', '—', '—']
        .map((state) => state === '—' ? state : `pages.backups.jobs.verification.${state}`))
    expect(table.querySelector('th[aria-sort]')?.getAttribute('aria-sort')).toBe('ascending')
})

for (const kind of ['destination', 'file']) {
    for (const dismiss of [false, true]) {
        it(`reports one ${kind} deletion error with dismissal=${dismiss}`, async () => {
            setup({ jobs: [completed()] })
            let reject!: (error: unknown) => void
            const operation = kind === 'destination' ? api.deleteBackupDestination : api.deleteBackupArtifact
            operation.mockReturnValueOnce(new Promise((_, fail) => { reject = fail }))
            const container = await render()
            const trigger = button(container, kind === 'destination' ? 'common.delete' : 'pages.backups.jobs.deleteFile')!
            await click(trigger)
            await click(button(container.querySelector('[role="dialog"]')!, kind === 'destination' ? 'common.delete' : 'pages.backups.jobs.deleteFile'))
            expect(operation).toHaveBeenCalledOnce()
            if (dismiss) {
                await click(button(container.querySelector('[role="dialog"]')!, 'common.close'))
                expect(container.querySelector('[role="dialog"]')).toBeNull()
            }
            expect(trigger.disabled).toBe(true)
            await act(async () => { reject({ isAxiosError: true, response: { data: { detail: 'Deletion failed' } } }) })
            await waitForCondition(() => pushToast.mock.calls.some(([message]) => message === 'Deletion failed'), 'failure toast after dismissal')
            await waitForCondition(() => container.querySelector('[role="dialog"]') === null, 'dialog completion')
            expect(pushToast).toHaveBeenCalledWith('Deletion failed', 'error')
            expect(pushToast).toHaveBeenCalledOnce()
            await waitForCondition(() => !trigger.disabled, 'delete trigger re-enabled')
        })
    }
}

describe('encryption status banner', () => {
    it('keeps cached status and operations usable after a failed status refetch', async () => {
        setup()
        const container = await render()
        api.fetchBackupStatus.mockRejectedValue(new Error('offline'))
        await act(async () => { await clients.get(container)!.invalidateQueries({ queryKey: queryKeys.backups.status() }) })
        await waitForCondition(() => container.querySelector('[role="status"]') !== null, 'cached status warning')
        expect(container.querySelector('.info-banner')?.textContent).toContain('pages.backups.status.encrypted')
        expect(button(container, 'pages.backups.jobs.backUpNow')).toBeDefined()
        expect(button(container, 'common.retry')).toBeDefined()
    })

    it('hides unknown status while independent backup operations remain available', async () => {
        setup({ jobs: [completed({ manifest_json: { kind: 'backup', zevs: [{ id: 'zev-1', name: 'Sonnenhof' }] } })] })
        api.fetchBackupStatus.mockReturnValue(new Promise(() => {}))
        const container = await render(false)
        expect(container.querySelector('.skeleton-block')).not.toBeNull()
        expect(container.textContent).not.toContain('pages.backups.status.never')
        expect(container.textContent).not.toContain('pages.backups.status.enabledDestinations')
        await waitForCondition(() => button(container, 'pages.backups.restore.preview')?.disabled === false, 'restore while status is loading')
        for (const section of ['destinations', 'schedule', 'jobs', 'restore']) {
            expect(container.textContent).toContain(`pages.backups.${section}.title`)
        }
        expect(container.textContent).toContain('nightly-disk')
        expect(api.fetchBackupDestinations).toHaveBeenCalled()
        expect(api.fetchBackupSchedule).toHaveBeenCalled()
        expect(api.fetchBackupJobs).toHaveBeenCalled()
        expect(api.fetchRestoreJobs).toHaveBeenCalled()
    })

    it('keeps independent operations available on initial status failure and offers retry', async () => {
        setup({ jobs: [completed({ manifest_json: { kind: 'backup', zevs: [{ id: 'zev-1', name: 'Sonnenhof' }] } })] })
        api.fetchBackupStatus.mockRejectedValueOnce(new Error('offline'))
        const container = await render()
        expect(container.querySelector('[role="alert"]')).not.toBeNull()
        expect(container.textContent).not.toContain('pages.backups.status.never')
        for (const section of ['destinations', 'schedule', 'jobs', 'restore']) {
            expect(container.textContent).toContain(`pages.backups.${section}.title`)
        }
        expect(button(container, 'pages.backups.restore.preview')?.disabled).toBe(false)
        await click(button(container, 'common.retry'))
        await waitForCondition(() => container.querySelector('.info-banner')?.textContent?.includes('pages.backups.status.encrypted') ?? false, 'recovered backup status')
        expect(container.querySelector('.info-banner')?.textContent).toContain('pages.backups.status.encrypted')
    })

    it('warns loudly that backups are not encrypted, and does not claim they are', async () => {
        setup({ statusData: status({ encrypted: false, encryption_required: false, encryption_key_fingerprint: '' }) })
        const container = await render()
        expect(container.querySelector('.warning-banner')?.textContent).toContain('pages.backups.status.unencryptedTitle')
        expect(container.querySelector('.info-banner')).toBeNull()
    })

    it('confirms encryption when a key is configured', async () => {
        setup()
        const container = await render()
        expect(container.querySelector('.info-banner')?.textContent).toContain('pages.backups.status.encrypted')
        expect(container.querySelector('.warning-banner')).toBeNull()
    })

    it('shows an unusable key as an error, not as "no key"', async () => {
        setup({ statusData: status({ encrypted: false, encryption_key_problem: 'too short' }) })
        const container = await render()
        expect(container.querySelector('.error-banner')?.textContent).toContain('pages.backups.status.keyProblem')
        expect(container.querySelector('.warning-banner')).toBeNull()
    })

    it('says backups cannot run when encryption is required but no key is set', async () => {
        setup({ statusData: status({ encrypted: false, encryption_required: true, encryption_key_fingerprint: '' }) })
        const container = await render()
        expect(container.querySelector('.error-banner')?.textContent).toContain('pages.backups.status.blockedTitle')
        expect(container.querySelector('.warning-banner')).toBeNull()
        expect(container.querySelector('.info-banner')).toBeNull()
    })

    it('evaluates a rejected key before the missing-key case', async () => {
        setup({ statusData: status({ encrypted: false, encryption_required: true, encryption_key_problem: 'too short' }) })
        const container = await render()
        expect(container.querySelector('.error-banner')?.textContent).toContain('pages.backups.status.keyProblem')
        expect(container.querySelector('.error-banner')?.textContent).not.toContain('pages.backups.status.blockedTitle')
    })

    it('points at the server command for restoring an instance and says single-community restore is not in the app yet', async () => {
        setup()
        expect((await render()).textContent).toContain('pages.backups.restoreNotice')
    })
})

describe('destinations', () => {
    it('lists each destination with its target', async () => {
        setup()
        const container = await render()
        expect(container.textContent).toContain('nightly-disk')
        expect(container.textContent).toContain('/var/backups/openzev')
    })

    it('shows an empty state when there are none', async () => {
        setup({ destinations: [] })
        expect((await render()).textContent).toContain('pages.backups.destinations.empty')
    })

    it('disables the secret field, and says why, when no encryption key is configured', async () => {
        setup({ statusData: status({ encrypted: false }) })
        const container = await render()
        await click(button(container, 'pages.backups.destinations.add'))
        setValue(container.querySelector<HTMLSelectElement>('select')!, 's3')
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
        const secret = container.querySelector<HTMLInputElement>('input[type="password"]')!
        expect(secret.disabled).toBe(true)
        expect(container.textContent).toContain('pages.backups.form.secretNeedsKey')
    })

    it('enables the secret field when a key is configured', async () => {
        setup()
        const container = await render()
        await click(button(container, 'pages.backups.destinations.add'))
        setValue(container.querySelector<HTMLSelectElement>('select')!, 's3')
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
        expect(container.querySelector<HTMLInputElement>('input[type="password"]')!.disabled).toBe(false)
    })

    it('tells the admin when the server supplies S3 credentials, since they override the form', async () => {
        setup({ statusData: status({ environment_credentials: true }) })
        const container = await render()
        await click(button(container, 'pages.backups.destinations.add'))
        setValue(container.querySelector<HTMLSelectElement>('select')!, 's3')
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
        expect(container.textContent).toContain('pages.backups.form.environmentCredentials')
    })

    it('creates a local destination with the request body the API expects', async () => {
        setup({ destinations: [] })
        api.createBackupDestination.mockResolvedValue(disk)
        const container = await render()
        await click(button(container, 'pages.backups.destinations.add'))

        setValue(labelled(container, 'pages.backups.form.name')!.querySelector('input')!, 'weekly')
        setValue(labelled(container, 'pages.backups.form.path')!.querySelector('input')!, '/mnt/backups')
        await act(async () => { container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })

        expect(api.createBackupDestination).toHaveBeenCalledTimes(1)
        expect(api.createBackupDestination.mock.calls[0][0]).toMatchObject({
            name: 'weekly', kind: 'local', path: '/mnt/backups', bucket: '', enabled: true,
        })
        expect(api.createBackupDestination.mock.calls[0][0]).not.toHaveProperty('secret_access_key')
    })

    it('shows the server\'s validation message inside the form instead of closing it', async () => {
        setup({ destinations: [] })
        api.createBackupDestination.mockRejectedValue({ response: { data: { path: ['The path must not be inside MEDIA_ROOT.'] } } })
        const container = await render()
        await click(button(container, 'pages.backups.destinations.add'))
        setValue(labelled(container, 'pages.backups.form.name')!.querySelector('input')!, 'bad')
        setValue(labelled(container, 'pages.backups.form.path')!.querySelector('input')!, '/x')
        await act(async () => { container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)) })
        expect(container.querySelector('.error-banner')).not.toBeNull()
        expect(container.querySelector('form')).not.toBeNull()
    })
})

describe('starting a backup', () => {
    it('cannot start without an enabled destination', async () => {
        setup({ destinations: [] })
        const container = await render()
        expect(button(container, 'pages.backups.jobs.backUpNow')!.disabled).toBe(true)
        expect(container.textContent).toContain('pages.backups.jobs.noDestination')
    })

    it('a disabled destination does not count', async () => {
        setup({ destinations: [{ ...disk, enabled: false }] })
        expect(button(await render(), 'pages.backups.jobs.backUpNow')!.disabled).toBe(true)
    })

    it('queues a whole-instance backup to the first enabled destination', async () => {
        setup()
        api.createBackupJob.mockResolvedValue(completed({ status: 'queued' }))
        const container = await render()
        await click(button(container, 'pages.backups.jobs.backUpNow'))
        expect(api.createBackupJob).toHaveBeenCalledWith({ scope: 'instance', destination_id: 'd-disk' })
    })

    it('disables Back up now with a visible reason when creation is blocked', async () => {
        setup({ statusData: status({ encrypted: false, encryption_required: true }) })
        const container = await render()
        expect(button(container, 'pages.backups.jobs.backUpNow')!.disabled).toBe(true)
        expect(container.textContent).toContain('pages.backups.jobs.blocked')
        expect(api.createBackupJob).not.toHaveBeenCalled()
    })

    it('disables Back up now when the key is unusable, keeping existing job actions usable', async () => {
        setup({
            statusData: status({ encrypted: false, encryption_key_problem: 'too short' }),
            jobs: [completed()],
        })
        const blob = new Blob(['zip'])
        api.downloadBackupArtifact.mockResolvedValue(blob)
        api.verifyBackupJob.mockResolvedValue(completed())
        const container = await render()
        expect(button(container, 'pages.backups.jobs.backUpNow')!.disabled).toBe(true)
        expect(container.textContent).toContain('pages.backups.jobs.blockedKeyProblem')
        const download = button(container, 'pages.backups.jobs.download')!
        const check = button(container, 'pages.backups.jobs.check')!
        const details = button(container, 'pages.backups.jobs.details')!
        expect(download.disabled).toBe(false)
        expect(check.disabled).toBe(false)
        await click(download)
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
        expect(api.downloadBackupArtifact).toHaveBeenCalledWith('j-1')
        expect(downloadBlob).toHaveBeenCalledWith(blob, 'openzev-backup-1.zip')
        await click(check)
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
        expect(api.verifyBackupJob).toHaveBeenCalledWith('j-1')
        await click(details)
        expect(container.textContent).toContain('pages.backups.details.title')
    })

    it('shows the server 409 detail when a stale allowed page submits', async () => {
        setup()
        const axiosError = {
            isAxiosError: true,
            response: { data: { code: 'backup_encryption_required', detail: 'Backups require encryption on this instance.' } },
        }
        const { default: axios } = await import('axios')
        vi.spyOn(axios, 'isAxiosError').mockReturnValue(true)
        api.createBackupJob.mockRejectedValue(axiosError)
        const container = await render()
        await click(button(container, 'pages.backups.jobs.backUpNow'))
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)) })
        expect(pushToast).toHaveBeenCalledWith('Backups require encryption on this instance.', 'error')
        vi.restoreAllMocks()
    })

    it('a single-community backup needs a community chosen first', async () => {
        setup()
        api.createBackupJob.mockResolvedValue(completed({ status: 'queued' }))
        const container = await render()
        const scope = labelled(container, 'pages.backups.jobs.scope')!.querySelector('select')!
        setValue(scope, 'zev')
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
        expect(button(container, 'pages.backups.jobs.backUpNow')!.disabled).toBe(true)

        setValue(labelled(container, 'pages.backups.jobs.zev')!.querySelector('select')!, 'zev-2')
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
        await click(button(container, 'pages.backups.jobs.backUpNow'))
        expect(api.createBackupJob).toHaveBeenCalledWith({ scope: 'zev', destination_id: 'd-disk', zev_id: 'zev-2' })
    })
})

describe('job list', () => {
    it('offers a download for a finished local archive and saves it under its own name', async () => {
        setup({ jobs: [completed()] })
        const blob = new Blob(['zip'])
        api.downloadBackupArtifact.mockResolvedValue(blob)
        const container = await render()
        await click(button(container, 'pages.backups.jobs.download'))
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
        expect(api.downloadBackupArtifact).toHaveBeenCalledWith('j-1')
        expect(downloadBlob).toHaveBeenCalledWith(blob, 'openzev-backup-1.zip')
    })

    it('does not offer a download for an S3 archive — it is fetched from the bucket', async () => {
        setup({ jobs: [completed({ archive_location: 's3://bucket/a.zip' })] })
        expect(button(await render(), 'pages.backups.jobs.download')).toBeUndefined()
    })

    it('flags an unencrypted archive with a warning badge, not a neutral one', async () => {
        setup({ jobs: [completed({ encrypted: false })] })
        const container = await render()
        const badge = Array.from(container.querySelectorAll('.badge')).find((b) => b.textContent === 'pages.backups.jobs.notEncrypted')
        expect(badge?.classList.contains('badge-warning')).toBe(true)
    })

    it('shows a failed job\'s reason', async () => {
        setup({ jobs: [completed({ status: 'failed', error_message: 'Access denied: these credentials cannot write.', archive_bytes: null })] })
        const container = await render()
        expect(container.textContent).toContain('Access denied: these credentials cannot write.')
        expect(button(container, 'pages.backups.jobs.details')).toBeUndefined()
    })

    it('opens the details of a finished backup', async () => {
        setup({ jobs: [completed()] })
        const container = await render()
        await click(button(container, 'pages.backups.jobs.details'))
        expect(container.textContent).toContain('pages.backups.details.title')
        expect(container.textContent).toContain('deadbeef')
    })

    it('shows an empty state before the first backup', async () => {
        setup()
        expect((await render()).textContent).toContain('pages.backups.jobs.empty')
    })
})
