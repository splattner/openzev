import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TokensSection } from '../src/features/account/TokensSection'
import type { AccessCredential, MyCredentialsResponse } from '../src/types/api'
import { renderWithProviders, setInputValue } from './helpers/render'
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
vi.mock('../src/lib/clipboard', () => ({ copyToClipboard: vi.fn().mockResolvedValue(true) }))
const auth = vi.hoisted(() => ({ role: 'user', isImpersonating: false }))
vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({
        isImpersonating: auth.isImpersonating,
        user: {
            role: auth.role,
            memberships: [
                {
                    zev: 'z1', zev_name: 'Sonnenhof', zev_disabled: false, zev_billing_interval: 'monthly', access: 'viewer',
                    participants: [{ id: 'p1', valid_from: '2025-01-01', valid_to: null, live: true }],
                },
            ],
        },
    }),
}))

const credentialsApi = vi.hoisted(() => ({
    fetchMyCredentials: vi.fn(),
    createAnalyticsToken: vi.fn(),
    revokeCredential: vi.fn(),
}))
vi.mock('../src/lib/api/credentials', () => credentialsApi)
const authApi = vi.hoisted(() => ({ createApiKey: vi.fn() }))
vi.mock('../src/lib/api/auth', () => authApi)
const zevApi = vi.hoisted(() => ({ fetchZevs: vi.fn() }))
vi.mock('../src/lib/api/zev', () => zevApi)
const supplementaryApi = vi.hoisted(() => ({ rotateSupplementaryPushToken: vi.fn() }))
vi.mock('../src/lib/api/supplementary', () => supplementaryApi)

const noScope = { zev: null, zev_name: null, participant: null, participant_name: null, metering_point: null, meter_id: null }
const row = (overrides: Partial<AccessCredential>): AccessCredential => ({
    kind: 'api_key', id: 'k1', name: 'Script', prefix: 'ozv_aaaa', access: 'read_only', held_by: 'account', scope: noScope,
    created_at: '2026-10-01T10:00:00Z', expires_at: null, last_used_at: null, status: 'active', actions: ['revoke'], manage_url: null,
    ...overrides,
})
const energy = row({
    kind: 'energy_push', id: 's1', name: 'Home Assistant', prefix: 'ozs_cccc', access: 'write_readings',
    scope: { ...noScope, zev: 'z1', zev_name: 'Sonnenhof', participant: 'p1', participant_name: 'Pia', metering_point: 'mp1', meter_id: 'CH-1' },
    created_at: null, actions: ['rotate', 'revoke'], manage_url: '/me/metering-points',
})
const analytics = row({
    kind: 'analytics', id: 'a1', name: 'Grafana', prefix: 'oza_bbbb', access: 'read',
    scope: { ...noScope, zev: 'z1', zev_name: 'Sonnenhof', participant: 'p1', participant_name: 'Pia' },
})

const cleanups: Array<() => void> = []
const onRevoke = vi.fn()
const onRotate = vi.fn()

function respond(credentials: AccessCredential[], canAnalytics = true) {
    const response: MyCredentialsResponse = { credentials, can_create: { api_key: true, analytics: canAnalytics } }
    credentialsApi.fetchMyCredentials.mockResolvedValue(response)
}

async function mount() {
    const view = await renderWithProviders(createElement(TokensSection, { onRevoke, onRotate }), cleanups)
    await waitForCondition(() => view.container.querySelector('[data-testid^="credential-"]') !== null || view.container.textContent!.includes('account.tokens.empty'), 'the list')
    return view
}

const buttons = (root: ParentNode) => Array.from(root.querySelectorAll<HTMLButtonElement>('button'))
const buttonWith = (root: ParentNode, label: string) => buttons(root).find((b) => b.textContent?.includes(label) || b.getAttribute('aria-label')?.includes(label))!
const click = (element: HTMLElement) => act(async () => { element.click() })

beforeEach(() => {
    vi.clearAllMocks()
    auth.role = 'user'
    auth.isImpersonating = false
    zevApi.fetchZevs.mockResolvedValue([
        { id: 'z1', name: 'Sonnenhof', disabled_at: null },
        { id: 'z2', name: 'Hölzliackerweg', disabled_at: null },
    ])
    respond([row({}), analytics, energy])
})
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

describe('TokensSection list', () => {
    it('lists the three kinds with type, access and scope', async () => {
        const { container } = await mount()

        expect(container.querySelector('[data-testid="credential-api_key"]')!.textContent).toContain('account.tokens.access.read_only')
        const analyticsRow = container.querySelector('[data-testid="credential-analytics"]')!.textContent!
        expect(analyticsRow).toContain('account.tokens.kind.analytics')
        expect(analyticsRow).toContain('Sonnenhof')
        expect(analyticsRow).toContain('account.tokens.scopeOnlyMine')
        const energyRow = container.querySelector('[data-testid="credential-energy_push"]')!.textContent!
        expect(energyRow).toContain('CH-1')
        expect(energyRow).toContain('account.tokens.createdUnknown')
        expect(container.textContent).toContain('ozv_aaaa…')
    })

    it('marks a ZEV-held push token as operated by the community', async () => {
        respond([row({
            kind: 'energy_push', id: 's2', name: 'Common area', prefix: 'ozs_dddd', access: 'write_readings', held_by: 'zev',
            scope: { ...noScope, zev: 'z1', zev_name: 'Sonnenhof', metering_point: 'mp9', meter_id: 'CH-9' },
            created_at: null, actions: ['rotate', 'revoke'], manage_url: '/metering/points',
        })])
        const { container } = await mount()

        const energyRow = container.querySelector('[data-testid="credential-energy_push"]')!.textContent!
        expect(energyRow).toContain('account.tokens.scopeHeldByZev')
        expect(energyRow).not.toContain('account.tokens.scopeWholeZev')
    })

    it('filters by type with the chips', async () => {
        const { container } = await mount()

        await click(buttonWith(container, 'account.tokens.kind.analytics'))

        expect(container.querySelector('[data-testid="credential-analytics"]')).not.toBeNull()
        expect(container.querySelector('[data-testid="credential-api_key"]')).toBeNull()
        expect(container.querySelector('[data-testid="credential-energy_push"]')).toBeNull()
    })

    it('flags a credential that expires soon or has expired', async () => {
        const soon = new Date(Date.now() + 3 * 86_400_000).toISOString()
        respond([row({ expires_at: soon })])
        const { container } = await mount()

        expect(container.textContent).toContain('account.apiKeys.expiringBadge')
    })

    it('says so when there is nothing yet', async () => {
        respond([])
        const { container } = await mount()

        expect(container.textContent).toContain('account.tokens.empty')
    })

    it('offers rotate and a link to the source for an energy token, and only revoke for the others', async () => {
        const { container } = await mount()

        const energyRow = container.querySelector<HTMLElement>('[data-testid="credential-energy_push"]')!
        expect(buttonWith(energyRow, 'account.tokens.rotate')).toBeDefined()
        expect(energyRow.querySelector('a')!.getAttribute('href')).toBe('/me/metering-points')
        const keyRow = container.querySelector<HTMLElement>('[data-testid="credential-api_key"]')!
        expect(buttons(keyRow).some((b) => b.textContent?.includes('account.tokens.rotate'))).toBe(false)
    })
})

describe('TokensSection actions', () => {
    it('revoking asks for confirmation first and names the kind', async () => {
        const { container } = await mount()

        await click(buttonWith(container.querySelector<HTMLElement>('[data-testid="credential-analytics"]')!, 'account.tokens.revokeNamed'))

        expect(onRevoke).toHaveBeenCalledOnce()
        expect(onRevoke.mock.calls[0][0]).toMatchObject({ name: 'Grafana', kind: 'analytics' })
        expect(credentialsApi.revokeCredential).not.toHaveBeenCalled()

        credentialsApi.revokeCredential.mockResolvedValue(undefined)
        await act(async () => { onRevoke.mock.calls[0][0].onConfirm() })

        expect(credentialsApi.revokeCredential.mock.calls[0][0]).toMatchObject({ kind: 'analytics', id: 'a1' })
        expect(pushToast).toHaveBeenCalledWith('account.tokens.revokeSuccess', 'success')
    })

    it('rotating an energy token shows the new token once', async () => {
        supplementaryApi.rotateSupplementaryPushToken.mockResolvedValue({ push_token: 'ozs_cccc_fresh', push_token_prefix: 'cccc' })
        const { container } = await mount()

        await click(buttonWith(container.querySelector<HTMLElement>('[data-testid="credential-energy_push"]')!, 'account.tokens.rotate'))
        await act(async () => { onRotate.mock.calls[0][0].onConfirm() })
        await waitForCondition(() => container.querySelector('[data-testid="push-token"]') !== null, 'the new token')

        expect(container.querySelector('[data-testid="push-token"]')!.textContent).toBe('ozs_cccc_fresh')
        expect(supplementaryApi.rotateSupplementaryPushToken).toHaveBeenCalledWith('s1')
    })
})

describe('TokensSection creating', () => {
    it.each([false, true])('explains disabled creation/rotation during impersonation with capabilities %s', async (canCreate) => {
        auth.isImpersonating = true
        credentialsApi.fetchMyCredentials.mockResolvedValue({
            credentials: [row({}), analytics, { ...energy, actions: ['revoke'] }],
            can_create: { api_key: canCreate, analytics: canCreate },
        })
        const { container } = await mount()

        for (const label of ['account.tokens.newApiKey', 'account.tokens.newAnalytics', 'account.tokens.rotate']) {
            const button = buttonWith(container, label)
            expect(button).toBeDefined()
            expect(button.disabled).toBe(true)
            expect(button.title).toBe('account.impersonationRestrictions')
            await click(button)
        }
        expect(container.querySelector('form')).toBeNull()
        expect(onRotate).not.toHaveBeenCalled()
        const revocations = buttons(container).filter((button) => button.getAttribute('aria-label')?.includes('account.tokens.revokeNamed'))
        expect(revocations).toHaveLength(3)
        expect(revocations.every((button) => !button.disabled)).toBe(true)
    })

    it('creates an API key and shows its secret once', async () => {
        authApi.createApiKey.mockResolvedValue({ id: 'k2', name: 'New', key: 'ozv_zzzz_secret', prefix: 'zzzz' })
        const { container } = await mount()

        await click(buttonWith(container, 'account.tokens.newApiKey'))
        await act(async () => { setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, 'Nightly export') })
        await click(buttonWith(container, 'account.apiKeys.create'))
        await waitForCondition(() => container.querySelector('[data-testid="api-key-secret"]') !== null, 'the secret')

        expect(authApi.createApiKey.mock.calls[0][0]).toMatchObject({ name: 'Nightly export', read_only: false })
        expect(container.querySelector('[data-testid="api-key-secret"]')!.textContent).toBe('ozv_zzzz_secret')
        await click(buttonWith(container, 'account.apiKeys.dismissSecret'))
        expect(container.querySelector('[data-testid="api-key-secret"]')).toBeNull()
    })

    it('creates an analytics token for the chosen scope and shows a ready-made command', async () => {
        credentialsApi.createAnalyticsToken.mockResolvedValue({ id: 'a2', name: 'Dash', zev: 'z1', participant: null, prefix: 'dddd', expires_at: null, token: 'oza_dddd_secret' })
        const { container } = await mount()

        await click(buttonWith(container, 'account.tokens.newAnalytics'))
        const select = container.querySelector<HTMLSelectElement>('select')!
        expect(Array.from(select.options).map((o) => o.value)).toEqual(['zev:z1', 'participant:z1:p1'])
        await act(async () => { setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, 'Dash') })
        await click(buttonWith(container, 'account.tokens.analytics.create'))
        await waitForCondition(() => container.querySelector('[data-testid="analytics-token-secret"]') !== null, 'the secret')

        expect(credentialsApi.createAnalyticsToken.mock.calls[0][0]).toMatchObject({ name: 'Dash', zev: 'z1', participant: null })
        expect(container.querySelector('[data-testid="analytics-token-secret"]')!.textContent).toBe('oza_dddd_secret')
        expect(container.textContent).toContain('Authorization: Bearer oza_dddd_secret')
    })

    it('a participant-scoped choice sends the participant', async () => {
        credentialsApi.createAnalyticsToken.mockResolvedValue({ id: 'a3', name: 'Me', zev: 'z1', participant: 'p1', prefix: 'eeee', expires_at: null, token: 'oza_eeee_x' })
        const { container } = await mount()

        await click(buttonWith(container, 'account.tokens.newAnalytics'))
        const select = container.querySelector<HTMLSelectElement>('select')!
        await act(async () => {
            select.value = 'participant:z1:p1'
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await act(async () => { setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, 'Me') })
        await click(buttonWith(container, 'account.tokens.analytics.create'))
        await waitForCondition(() => credentialsApi.createAnalyticsToken.mock.calls.length > 0, 'the request')

        expect(credentialsApi.createAnalyticsToken.mock.calls[0][0]).toMatchObject({ zev: 'z1', participant: 'p1' })
    })

    it('lets an administrator pick any community, not only their own', async () => {
        auth.role = 'admin'
        credentialsApi.createAnalyticsToken.mockResolvedValue({ id: 'a4', name: 'Any', zev: 'z2', participant: null, prefix: 'ffff', expires_at: null, token: 'oza_ffff_x' })
        const { container } = await mount()

        await click(buttonWith(container, 'account.tokens.newAnalytics'))
        await waitForCondition(() => container.querySelector('select')!.options.length === 3, 'every community')
        const select = container.querySelector<HTMLSelectElement>('select')!
        expect(Array.from(select.options).map((o) => o.value).sort()).toEqual(['participant:z1:p1', 'zev:z1', 'zev:z2'])

        await act(async () => {
            select.value = 'zev:z2'
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await act(async () => { setInputValue(container.querySelector<HTMLInputElement>('input[type="text"]')!, 'Any') })
        await click(buttonWith(container, 'account.tokens.analytics.create'))
        await waitForCondition(() => credentialsApi.createAnalyticsToken.mock.calls.length > 0, 'the request')

        expect(credentialsApi.createAnalyticsToken.mock.calls[0][0]).toMatchObject({ zev: 'z2', participant: null })
    })

    it('does not look up every community for an ordinary account', async () => {
        const { container } = await mount()

        await click(buttonWith(container, 'account.tokens.newAnalytics'))

        expect(zevApi.fetchZevs).not.toHaveBeenCalled()
    })

    it('hides the analytics entry when the account cannot create one', async () => {
        respond([row({})], false)
        const { container } = await mount()

        expect(buttons(container).some((b) => b.textContent?.includes('account.tokens.newAnalytics'))).toBe(false)
        expect(buttonWith(container, 'account.tokens.newApiKey')).toBeDefined()
    })

    it('points to the energy data page instead of creating an energy token', async () => {
        const { container } = await mount()

        const link = Array.from(container.querySelectorAll('a')).find((a) => a.textContent?.includes('account.tokens.energyDataLink'))!
        expect(link.getAttribute('href')).toBe('/me/metering-points')
    })
})
