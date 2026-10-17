import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AdminCredentialsPage } from '../src/pages/AdminCredentialsPage'
import type { AdminAccessCredential } from '../src/types/api'
import { renderWithProviders } from './helpers/render'
import { waitForCondition } from './helpers/waitForCondition'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options ? `${key}${JSON.stringify(options)}` : key) }),
}))
const pushToast = vi.fn()
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, useAppSettings: () => ({ settings: actual.DEFAULT_APP_SETTINGS, isLoading: false }) }
})

const credentialsApi = vi.hoisted(() => ({ fetchAllCredentials: vi.fn(), revokeCredential: vi.fn() }))
vi.mock('../src/lib/api/credentials', () => credentialsApi)
const authApi = vi.hoisted(() => ({ fetchUsers: vi.fn() }))
vi.mock('../src/lib/api/auth', () => authApi)

const noScope = { zev: null, zev_name: null, participant: null, participant_name: null, metering_point: null, meter_id: null }
const row = (overrides: Partial<AdminAccessCredential>): AdminAccessCredential => ({
    kind: 'api_key', id: 'k1', name: 'Script', prefix: 'ozv_aaaa', access: 'read_write', scope: noScope, created_at: null,
    expires_at: null, last_used_at: null, status: 'active', actions: ['revoke'], manage_url: null,
    owner: { id: 7, username: 'pia', email: 'pia@example.com' }, revoked_at: null, ...overrides,
})

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => {
    vi.clearAllMocks()
    authApi.fetchUsers.mockResolvedValue([{ id: 7, username: 'pia', email: 'pia@example.com' }])
    credentialsApi.fetchAllCredentials.mockResolvedValue([
        row({}),
        row({ kind: 'analytics', id: 'a1', name: 'Grafana', prefix: 'oza_bbbb', access: 'read', scope: { ...noScope, zev: 'z', zev_name: 'Sonnenhof' } }),
        row({ kind: 'energy_push', id: 's1', name: 'HA', prefix: 'ozs_cccc', access: 'write_readings', actions: ['rotate', 'revoke'] }),
        row({ id: 'k2', name: 'Old', status: 'revoked', revoked_at: '2026-10-01T00:00:00Z' }),
    ])
})

const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]')
const click = (element: HTMLElement) => act(async () => { element.click() })

async function mount() {
    const view = await renderWithProviders(createElement(AdminCredentialsPage, { embedded: true }), cleanups)
    await waitForCondition(() => view.container.querySelector('table') !== null, 'the table')
    return view
}

describe('AdminCredentialsPage', () => {
    it('lists every kind with owner, type and scope, and counts them by status', async () => {
        const { container } = await mount()

        const text = container.textContent!
        expect(text).toContain('Script')
        expect(text).toContain('account.tokens.kind.analytics')
        expect(text).toContain('account.tokens.kind.energy_push')
        expect(text).toContain('Sonnenhof')
        expect(text).toContain('pia@example.com')
        expect(container.querySelectorAll('tbody tr')).toHaveLength(4)
        const stats = Array.from(container.querySelectorAll('.stat-grid > *')).map((n) => n.textContent)
        expect(stats.join('|')).toMatch(/pages.adminCredentials.statActive.*3/)
        expect(stats.join('|')).toMatch(/pages.adminCredentials.statRevoked.*1/)
    })

    it('offers revoke only for credentials that are not revoked', async () => {
        const { container } = await mount()

        const rows = Array.from(container.querySelectorAll('tbody tr'))
        const revoked = rows.find((r) => r.textContent!.includes('Old'))!
        expect(revoked.querySelector('button')).toBeNull()
        expect(rows.filter((r) => r.querySelector('button'))).toHaveLength(3)
    })

    it('revokes through the kind of the credential, as admin, after confirmation', async () => {
        credentialsApi.revokeCredential.mockResolvedValue(undefined)
        const { container } = await mount()
        const analyticsRow = Array.from(container.querySelectorAll('tbody tr')).find((r) => r.textContent!.includes('Grafana'))!

        await click(analyticsRow.querySelector('button')!)
        expect(dialog()!.textContent).toContain('pages.adminCredentials.revokeConfirmMessage.analytics')
        expect(credentialsApi.revokeCredential).not.toHaveBeenCalled()

        const confirm = Array.from(dialog()!.querySelectorAll('button')).find((b) => b.textContent?.includes('pages.adminCredentials.revoke'))!
        await click(confirm)

        expect(credentialsApi.revokeCredential.mock.calls[0][0]).toMatchObject({ kind: 'analytics', id: 'a1' })
        expect(credentialsApi.revokeCredential.mock.calls[0][1]).toEqual({ asAdmin: true })
    })

    it('asks the server for the chosen type and status', async () => {
        const { container } = await mount()
        const selects = container.querySelectorAll<HTMLSelectElement>('select')
        const kind = Array.from(selects).find((s) => Array.from(s.options).some((o) => o.value === 'energy_push'))!

        await act(async () => {
            kind.value = 'energy_push'
            kind.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await waitForCondition(() => credentialsApi.fetchAllCredentials.mock.calls.some(([f]) => f.kind === 'energy_push'), 'the filtered request')

        expect(credentialsApi.fetchAllCredentials).toHaveBeenLastCalledWith({ user: '', kind: 'energy_push', status: '' })
    })
})
