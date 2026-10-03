import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import type { Party, ZevAccessGrant } from '../src/types/api'

// ZEV settings → People & access (#761): roles, access and contacts on one tab.

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, values?: Record<string, string>) => (values?.role ? `${key}:${values.role}` : key) }),
}))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1 }, refreshUser: vi.fn() }) }))
vi.mock('../src/lib/dates', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../src/lib/dates')>()),
    todayBusinessIso: () => '2026-06-15',
}))
vi.mock('../src/lib/appSettings', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../src/lib/appSettings')>()),
    useAppSettings: () => ({ settings: { date_format_short: 'dd.MM.yyyy' } }),
}))
vi.mock('../src/lib/api/zev', () => ({
    fetchParties: vi.fn(),
    fetchPartyRoles: vi.fn(() => Promise.resolve([])),
    fetchZevAccess: vi.fn(),
    createParty: vi.fn(),
    updateParty: vi.fn(),
    deleteParty: vi.fn(),
    assignPartyRole: vi.fn(),
    endPartyRole: vi.fn(),
    createZevAccess: vi.fn(),
    updateZevAccess: vi.fn(),
    revokeZevAccess: vi.fn(),
    resendZevInvitation: vi.fn(),
}))

import { fetchParties, fetchZevAccess } from '../src/lib/api/zev'
import { ZevPeopleSection } from '../src/features/zev/ZevPeopleSection'

const account = { id: 7, email: 'paula@example.com', first_name: 'Paula', last_name: 'Producer', pending_invitation: false }
const grant: ZevAccessGrant = {
    id: 'g1', zev: 'z1', role: 'manager', valid_from: '2026-01-01', valid_to: null, is_active: true,
    granted_by: null, created_at: '', user: account, source: 'grant',
}
const viaRole: ZevAccessGrant = {
    ...grant, id: 'role-r1-7', source: 'role',
    party_role: { role: 'issuer', party: 'p1', party_display_name: 'Paula Producer' },
}
const contact: Party = {
    id: 'c1', zev: 'z1', kind: 'organisation', title: '', first_name: '', last_name: '', organisation_name: 'Verwaltung Nord',
    name_addition: '', email: 'nord@example.com', phone: '', address_line1: '', address_line2: '', postal_code: '', city: '',
    notes: '', display_name: 'Verwaltung Nord', participations: [], roles: [], accounts: [], created_at: '', updated_at: '',
}

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchZevAccess).mockResolvedValue([grant, viaRole])
    vi.mocked(fetchParties).mockResolvedValue([contact])
})

async function render() {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(
        createElement(MantineProvider, null,
            createElement(QueryClientProvider, { client }, createElement(ZevPeopleSection, { zevId: 'z1', canManage: true }))),
    ))
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
    return container
}

describe('ZevPeopleSection', () => {
    it('shows roles, access and contacts, one access row per login', async () => {
        const container = await render()
        const cards = container.querySelectorAll('section.card')
        expect(cards).toHaveLength(3)
        const rows = cards[1].querySelectorAll('.zev-access-row')
        expect(rows).toHaveLength(1)
        expect(rows[0].textContent).toContain('pages.zevSettings.access.byRole:pages.participants.roles.issuer')
        expect(cards[2].textContent).toContain('Verwaltung Nord')
    })

    it('gives a contact access from its own row', async () => {
        const container = await render()
        const giveAccess = Array.from(container.querySelectorAll('section.card')[2].querySelectorAll('button'))
            .find((button) => button.textContent?.includes('pages.zevSettings.access.add'))!
        await act(async () => { giveAccess.click() })
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
        const selects = container.querySelectorAll<HTMLSelectElement>('#zev-access-section .zev-access-form select')
        expect(selects[0].value).toBe('party')
        expect(selects[1].value).toBe('c1')
    })
})
