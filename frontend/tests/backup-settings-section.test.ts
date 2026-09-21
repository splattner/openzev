import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { BackupSettingsSection } from '../src/features/backups/BackupSettingsSection'
import type { BackupDestination, BackupJob, BackupStatus } from '../src/types/api'

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
}))
vi.mock('../src/lib/api/backups', () => api)
vi.mock('../src/lib/api/zev', () => ({
    fetchZevs: vi.fn().mockResolvedValue([{ id: 'zev-1', name: 'Sonnenhof' }, { id: 'zev-2', name: 'Bergblick' }]),
}))
const downloadBlob = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/downloadBlob', () => ({ downloadBlob }))

const status = (overrides: Partial<BackupStatus> = {}): BackupStatus => ({
    encrypted: true, encryption_key_fingerprint: 'abc123', encryption_key_problem: '', environment_credentials: false,
    destinations_enabled: 1, last_successful: null, last_failed: null, age_hours: null, ...overrides,
})

const disk: BackupDestination = {
    id: 'd-disk', name: 'nightly-disk', kind: 'local', enabled: true, path: '/var/backups/openzev', bucket: '', prefix: '',
    region: '', endpoint_url: '', access_key_id: '', server_side_encryption: 'AES256', credential_mode: 'instance_role',
    has_secret_access_key: false, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const completed = (overrides: Partial<BackupJob> = {}): BackupJob => ({
    id: 'j-1', scope: 'instance', zev_id: null, zev_name: '', trigger: 'manual', destination_id: 'd-disk',
    destination_name: 'nightly-disk', status: 'completed', created_at: '2026-09-21T04:00:00Z',
    started_at: '2026-09-21T04:00:00Z', completed_at: '2026-09-21T04:01:00Z', archive_name: 'openzev-backup-1.zip',
    archive_location: '/var/backups/openzev/openzev-backup-1.zip', archive_bytes: 2048, archive_sha256: 'deadbeef',
    encrypted: true, encryption_key_fingerprint: 'abc123', manifest_json: {}, error_message: '', ...overrides,
})

function setup({ statusData = status(), destinations = [disk], jobs = [] as BackupJob[] } = {}) {
    api.fetchBackupStatus.mockResolvedValue(statusData)
    api.fetchBackupDestinations.mockResolvedValue(destinations)
    api.fetchBackupJobs.mockResolvedValue(jobs)
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
    // Let the status / destination / job queries settle.
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)) })
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

describe('encryption status banner', () => {
    it('warns loudly that backups are not encrypted, and does not claim they are', async () => {
        setup({ statusData: status({ encrypted: false, encryption_key_fingerprint: '' }) })
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

    it('says plainly that restore is not available in the app yet', async () => {
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
