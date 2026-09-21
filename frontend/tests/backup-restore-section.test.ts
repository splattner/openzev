import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { BackupRestoreSection } from '../src/features/backups/BackupRestoreSection'
import type { BackupDestination, BackupJob, RestoreConflict, RestoreJob, RestorePlan } from '../src/types/api'

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
    fetchBackupJobs: vi.fn(),
    fetchBackupDestinations: vi.fn(),
    fetchRestoreJobs: vi.fn(),
    fetchRestoreJob: vi.fn(),
    createRestoreJob: vi.fn(),
}))
vi.mock('../src/lib/api/backups', () => api)

const disk: BackupDestination = {
    id: 'd-disk', name: 'nightly-disk', kind: 'local', enabled: true, path: '/var/backups/openzev', bucket: '', prefix: '',
    region: '', endpoint_url: '', access_key_id: '', server_side_encryption: 'AES256', credential_mode: 'instance_role',
    has_secret_access_key: false, created_at: '', updated_at: '',
}
const other: BackupDestination = { ...disk, id: 'd-other', name: 'offsite' }

const zevEntry = (id: string, name: string) => ({ id, name, counts: {}, media: { files: 0, bytes: 0, missing: [], unsafe: [] } })
const backup = (overrides: Partial<BackupJob> = {}): BackupJob => ({
    id: 'b1', scope: 'instance', zev_id: null, zev_name: '', trigger: 'manual', destination_id: 'd-disk',
    destination_name: 'nightly-disk', status: 'completed', created_at: '2026-09-21T04:00:00Z', started_at: null,
    completed_at: '2026-09-21T04:01:00Z', archive_name: 'a.zip', archive_location: '/var/backups/a.zip', archive_bytes: 1,
    archive_sha256: '', encrypted: false, encryption_key_fingerprint: '', error_message: '',
    manifest_json: {
        kind: 'backup', scope: 'instance', zevs: [zevEntry('z1', 'Sonnenhof'), zevEntry('z2', 'Bergblick')], counts: {},
    } as unknown as BackupJob['manifest_json'],
    ...overrides,
})

const plan = (overrides: Partial<RestorePlan> = {}): RestorePlan => ({
    zev: { id: 'z1', name: 'Sonnenhof', exists_now: true, current_name: 'Sonnenhof' },
    backup: { created_at: '2026-09-21T04:00:00+02:00', scope: 'instance', instance_name: '', openzev_version: '1.0.0' },
    sections: {
        zev: { backup: 1, current: 1, kept: false },
        readings: { backup: 100, current: 40, kept: false },
        audit_events: { backup: 5, current: 9, kept: true },
    },
    accounts: { relink: 3, missing: [] },
    media: { files: 2, missing: 0 },
    conflicts: [],
    blocked: false,
    safety_backup_id: null,
    restored: null,
    ...overrides,
})

const job = (overrides: Partial<RestoreJob> = {}): RestoreJob => ({
    id: 'r1', target_zev_id: 'z1', target_zev_name: 'Sonnenhof', source_backup_id: 'b1', source_archive_name: 'a.zip',
    source_created_at: '2026-09-21T04:00:00+02:00', source_description: '', dry_run: true, force: false, status: 'completed',
    plan_json: plan(), safety_backup_id: null, created_at: '2026-09-21T05:00:00Z', started_at: null, completed_at: null,
    error_message: '', ...overrides,
})

const soft: RestoreConflict = { kind: 'sent_invoice_deleted', detail: 'INV-1 (paid)', overridable: true }
const hard: RestoreConflict = { kind: 'meter_id_owned_by_other_zev', detail: 'ALPHA-1 → Beta', overridable: false }

function setup({ backups = [backup()], destinations = [disk, other], history = [] as RestoreJob[] } = {}) {
    api.fetchBackupJobs.mockResolvedValue(backups)
    api.fetchBackupDestinations.mockResolvedValue(destinations)
    api.fetchRestoreJobs.mockResolvedValue(history)
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
            createElement(MantineProvider, null, createElement(BackupRestoreSection))),
    ))
    await settle()
    return container
}

const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)) })

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
    await settle()
}

const selects = (container: Element) => Array.from(container.querySelectorAll('select'))
const confirmInput = (container: Element) => container.querySelector<HTMLInputElement>('input[autocomplete="off"]')

/** Preview a restore and resolve with the finished preview job. */
async function preview(container: Element, finished: RestoreJob = job()) {
    api.createRestoreJob.mockResolvedValue({ ...finished, status: 'queued', plan_json: {} })
    api.fetchRestoreJob.mockResolvedValue(finished)
    await click(button(container, 'pages.backups.restore.preview'))
}

describe('choosing what to restore', () => {
    it('says so when there is no finished backup, and offers no form', async () => {
        setup({ backups: [backup({ status: 'failed' })] })
        const container = await render()
        expect(container.textContent).toContain('pages.backups.restore.noBackups')
        expect(button(container, 'pages.backups.restore.preview')).toBeUndefined()
    })

    it('lists the communities of the chosen backup, and follows it when the backup changes', async () => {
        const small = backup({
            id: 'b2', scope: 'zev',
            manifest_json: { kind: 'backup', scope: 'zev', zevs: [zevEntry('z9', 'Only One')], counts: {} } as unknown as BackupJob['manifest_json'],
        })
        setup({ backups: [backup(), small] })
        const container = await render()
        const [backupSelect, communitySelect] = selects(container)
        expect(Array.from(communitySelect.options).map((o) => o.textContent)).toEqual(['Sonnenhof', 'Bergblick'])
        await act(async () => setValue(backupSelect, 'b2'))
        expect(Array.from(selects(container)[1].options).map((o) => o.textContent)).toEqual(['Only One'])
    })

    it('never offers to restore the whole instance', async () => {
        setup()
        const container = await render()
        expect(container.textContent).toContain('pages.backups.restore.description')
        expect(container.textContent).not.toContain('instance restore')
    })
})

describe('previewing', () => {
    it('asks the server for a dry run of the chosen community and shows the plan it returns', async () => {
        setup()
        const container = await render()
        await preview(container)
        expect(api.createRestoreJob).toHaveBeenCalledWith({ source_backup_id: 'b1', target_zev_id: 'z1', dry_run: true })
        expect(container.textContent).toContain('pages.backups.restore.sections.readings')
        expect(container.textContent).toContain('pages.backups.restore.plan.kept')
        expect(container.textContent).toContain('100')
    })

    it('names accounts that would be left unlinked', async () => {
        setup()
        const container = await render()
        await preview(container, job({ plan_json: plan({ accounts: { relink: 1, missing: ['gone@example.com'] } }) }))
        expect(container.querySelector('.warning-banner')?.textContent).toContain('pages.backups.restore.plan.missingAccountsTitle')
    })

    it('shows a preview error from the server as a toast', async () => {
        setup()
        api.createRestoreJob.mockRejectedValue(new Error('boom'))
        const container = await render()
        await click(button(container, 'pages.backups.restore.preview'))
        expect(pushToast).toHaveBeenCalledWith(expect.any(String), 'error')
    })

    it('reports a restore that was refused, with the reason and the conflicts', async () => {
        setup()
        const container = await render()
        await preview(container, job({
            status: 'failed', error_message: 'The restore was refused: 1 problem(s).', plan_json: plan({ conflicts: [hard], blocked: true }),
        }))
        expect(container.querySelector('.error-banner')?.textContent).toContain('The restore was refused')
        expect(container.textContent).toContain('pages.backups.restore.conflict.meter_id_owned_by_other_zev')
        expect(button(container, 'pages.backups.restore.apply')).toBeUndefined()
    })

    it('lists why a damaged archive was refused', async () => {
        setup()
        const container = await render()
        await preview(container, job({
            status: 'failed', error_message: 'The backup failed verification.', plan_json: { verification_failures: ['stowaway.txt: present but not in the manifest'] },
        }))
        expect(container.textContent).toContain('stowaway.txt')
    })
})

describe('applying', () => {
    it('is not offered until the community\'s name has been typed', async () => {
        setup()
        const container = await render()
        await preview(container)
        const apply = () => button(container, 'pages.backups.restore.apply')!
        expect(apply().disabled).toBe(true)
        await act(async () => setValue(confirmInput(container)!, 'sonnenhof'))
        expect(apply().disabled).toBe(true) // case matters: it is the name being overwritten
        await act(async () => setValue(confirmInput(container)!, 'Sonnenhof'))
        expect(apply().disabled).toBe(false)
    })

    it('starts a real restore with the safety destination, and no force unless asked', async () => {
        setup()
        const container = await render()
        await preview(container)
        await act(async () => setValue(confirmInput(container)!, 'Sonnenhof'))
        api.createRestoreJob.mockResolvedValue(job({ id: 'r2', dry_run: false, status: 'queued', plan_json: {} }))
        await click(button(container, 'pages.backups.restore.apply'))
        expect(api.createRestoreJob).toHaveBeenLastCalledWith({
            source_backup_id: 'b1', target_zev_id: 'z1', dry_run: false, force: false, safety_destination_id: 'd-disk',
        })
    })

    it('lets the safety backup go somewhere else', async () => {
        setup()
        const container = await render()
        await preview(container)
        await act(async () => setValue(confirmInput(container)!, 'Sonnenhof'))
        const safety = selects(container).find((s) => Array.from(s.options).some((o) => o.textContent === 'offsite'))!
        await act(async () => setValue(safety, 'd-other'))
        api.createRestoreJob.mockResolvedValue(job({ id: 'r2', dry_run: false, status: 'queued', plan_json: {} }))
        await click(button(container, 'pages.backups.restore.apply'))
        expect(api.createRestoreJob.mock.calls.at(-1)![0].safety_destination_id).toBe('d-other')
    })

    it('asks for no safety backup when the community no longer exists', async () => {
        setup()
        const container = await render()
        const gone = plan({ zev: { id: 'z1', name: 'Sonnenhof', exists_now: false, current_name: '' } })
        await preview(container, job({ plan_json: gone }))
        expect(container.textContent).not.toContain('pages.backups.restore.safetyDestination')
        expect(container.textContent).toContain('pages.backups.restore.warningNew')
        await act(async () => setValue(confirmInput(container)!, 'Sonnenhof'))
        api.createRestoreJob.mockResolvedValue(job({ id: 'r2', dry_run: false, status: 'queued', plan_json: {} }))
        await click(button(container, 'pages.backups.restore.apply'))
        expect(api.createRestoreJob.mock.calls.at(-1)![0]).not.toHaveProperty('safety_destination_id')
    })

    it('needs the force switch as well when issued invoices or contracts would be lost', async () => {
        setup()
        const container = await render()
        await preview(container, job({ plan_json: plan({ conflicts: [soft] }) }))
        await act(async () => setValue(confirmInput(container)!, 'Sonnenhof'))
        const apply = () => button(container, 'pages.backups.restore.apply')!
        expect(apply().disabled).toBe(true)
        await click(container.querySelector('input[type="checkbox"]'))
        expect(apply().disabled).toBe(false)
        api.createRestoreJob.mockResolvedValue(job({ id: 'r2', dry_run: false, force: true, status: 'queued', plan_json: {} }))
        await click(apply())
        expect(api.createRestoreJob.mock.calls.at(-1)![0].force).toBe(true)
    })

    it('offers no way forward at all past a problem that cannot be overridden', async () => {
        setup()
        const container = await render()
        await preview(container, job({ plan_json: plan({ conflicts: [hard], blocked: true }) }))
        expect(container.textContent).toContain('pages.backups.restore.blocked')
        expect(button(container, 'pages.backups.restore.apply')).toBeUndefined()
        expect(container.querySelector('input[type="checkbox"]')).toBeNull()
    })

    it('reports a finished restore and refreshes what the rest of the app has cached', async () => {
        setup()
        const container = await render()
        await preview(container)
        await act(async () => setValue(confirmInput(container)!, 'Sonnenhof'))
        const finished = job({
            id: 'r2', dry_run: false, plan_json: plan({ restored: { 'zev.Zev': 1, 'metering.MeterReading': 100 }, safety_backup_id: 's1' }),
        })
        api.createRestoreJob.mockResolvedValue({ ...finished, status: 'queued', plan_json: {} })
        api.fetchRestoreJob.mockResolvedValue(finished)
        const before = api.fetchBackupJobs.mock.calls.length
        await click(button(container, 'pages.backups.restore.apply'))
        await settle()
        expect(container.querySelector('.success-banner')?.textContent).toContain('pages.backups.restore.done')
        expect(container.querySelector('.success-banner')?.textContent).toContain('pages.backups.restore.safetyTaken')
        expect(api.fetchBackupJobs.mock.calls.length).toBeGreaterThan(before)
    })

    it('goes back to the start when a different community is chosen', async () => {
        setup()
        const container = await render()
        await preview(container)
        expect(confirmInput(container)).toBeTruthy()
        await act(async () => setValue(selects(container)[1], 'z2'))
        expect(confirmInput(container)).toBeNull()
    })
})

describe('history', () => {
    it('lists earlier restores with their kind, whether forced, and how they ended', async () => {
        setup({
            history: [
                job({ id: 'h1', dry_run: false, force: true, status: 'failed', error_message: 'The safety backup failed' }),
                job({ id: 'h2', dry_run: true }),
            ],
        })
        const container = await render()
        const rows = container.querySelectorAll('tbody tr')
        expect(rows).toHaveLength(2)
        expect(rows[0].textContent).toContain('pages.backups.restore.kindRestore')
        expect(rows[0].textContent).toContain('pages.backups.restore.forced')
        expect(rows[0].textContent).toContain('The safety backup failed')
        expect(rows[1].textContent).toContain('pages.backups.restore.kindPreview')
    })

    it('is absent when there is none', async () => {
        setup()
        const container = await render()
        expect(container.textContent).not.toContain('pages.backups.restore.history')
    })
})
