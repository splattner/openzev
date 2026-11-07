import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import type { Party, ZevAccessGrant, ZevPartyRole } from '../src/types/api'

// ZEV settings → People & access (#761): every person's access on its own row.

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, values?: Record<string, string>) => (values?.name ? `${key}:${values.name}` : key) }),
}))
const pushToast = vi.fn()
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
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
    fetchPartyRoles: vi.fn(),
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

import { createZevAccess, fetchParties, fetchPartyRoles, fetchZevAccess, revokeZevAccess, updateZevAccess } from '../src/lib/api/zev'
import { ZevPeopleSection } from '../src/features/zev/ZevPeopleSection'
import { waitForCondition } from './helpers/waitForCondition'

const user = (id: number, email: string) => ({ id, email, first_name: '', last_name: '', pending_invitation: false })
const party = (id: string, name: string, over: Partial<Party> = {}): Party => ({
    id, zev: 'z1', kind: 'person', title: '', first_name: '', last_name: name, organisation_name: '', name_addition: '',
    email: '', phone: '', address_line1: '', address_line2: '', postal_code: '', city: '', notes: '',
    display_name: name, participations: [], roles: [], accounts: [], created_at: '', updated_at: '', ...over,
})
const role = (id: string, partyId: string, name: string, kind: ZevPartyRole['role']): ZevPartyRole => ({
    id, zev: 'z1', party: partyId, party_display_name: name, role: kind, valid_from: '2026-01-01', valid_to: null,
    created_at: '', updated_at: '',
})
const entry = (id: string, account: ReturnType<typeof user>, over: Partial<ZevAccessGrant> = {}): ZevAccessGrant => ({
    id, zev: 'z1', role: 'manager', valid_from: '2026-01-01', valid_to: null, is_active: true, granted_by: null,
    created_at: '', user: account, source: 'grant', ...over,
})

const paula = user(7, 'paula@example.com')
const lena = user(8, 'lena@example.com')
const bookkeeper = user(9, 'books@example.com')

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchParties).mockResolvedValue([
        party('p1', 'Paula', { participations: [{ id: 'x', valid_from: '2026-01-01', valid_to: null }], accounts: [{ id: 7, email: paula.email, full_name: '', is_active: true }] }),
        party('p2', 'Lena', { participations: [{ id: 'y', valid_from: '2026-01-01', valid_to: null }], accounts: [{ id: 8, email: lena.email, full_name: '', is_active: true }] }),
        party('c1', 'Verwaltung Nord', { kind: 'organisation', organisation_name: 'Verwaltung Nord', email: 'nord@example.com' }),
    ])
    vi.mocked(fetchPartyRoles).mockResolvedValue([role('r1', 'p1', 'Paula', 'issuer'), role('r2', 'p2', 'Lena', 'landowner')])
    vi.mocked(fetchZevAccess).mockResolvedValue([
        entry('role-r1-7', paula, { source: 'role', party_role: { role: 'issuer', party: 'p1', party_display_name: 'Paula' } }),
        entry('g9', bookkeeper, { role: 'viewer' }),
    ])
    vi.mocked(createZevAccess).mockResolvedValue({ ...entry('g10', lena, { role: 'viewer' }), email_sent: true })
    vi.mocked(updateZevAccess).mockResolvedValue(entry('g9', bookkeeper))
    vi.mocked(revokeZevAccess).mockResolvedValue(undefined)
})

async function render(canManage = true) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(
        createElement(MantineProvider, null,
            createElement(QueryClientProvider, { client }, createElement(ZevPeopleSection, { zevId: 'z1', canManage }))),
    ))
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
    return container
}

// A person is a row of the contacts table or of the roles sheet.
const rowOf = (container: Element, name: string) =>
    Array.from(container.querySelectorAll('tr.people-row, .zev-role-row')).find((row) => row.textContent?.includes(name))!
const button = (row: Element, label: string) =>
    Array.from(row.querySelectorAll('button')).find((item) => item.textContent?.includes(label))!
const menuItem = (label: string) =>
    Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]')).find((item) => item.textContent?.includes(label))
async function openMenu(row: Element, label: string) {
    await act(async () => row.querySelector<HTMLButtonElement>('button[aria-haspopup="menu"]')!.click())
    await waitForCondition(() => menuItem(label) !== undefined, `menu item ${label}`)
    return menuItem(label)!
}
const levelSelect = (form: Element) =>
    Array.from(form.querySelectorAll('select')).find((select) => Array.from(select.options).some((option) => option.value === 'manager'))!

describe('ZevPeopleSection', () => {
    it('has no separate access area: the issuer row shows the login that manages', async () => {
        const container = await render()
        // Two sheets (roles, other people), no third list of who has access.
        expect(container.querySelectorAll('section.card, section.table-card')).toHaveLength(2)
        const issuer = rowOf(container, 'Paula')
        // The role heading says the login manages; the row names the login without a tag.
        expect(issuer.textContent).not.toContain('pages.zevSettings.access.managesByRole')
        expect(issuer.textContent).toContain('paula@example.com')
    })

    it('gives a landowner read-only access under its own row', async () => {
        const container = await render()
        const landowner = rowOf(container, 'Lena')
        expect(landowner.textContent).toContain('pages.zevSettings.access.none')
        await act(async () => { button(landowner, 'pages.zevSettings.access.add').click() })
        const form = container.querySelector<HTMLFormElement>('.zev-access-form')!
        // The form opens where the person is, with the person chosen: only the level is left.
        expect(landowner.closest('li')!.contains(form)).toBe(true)
        await act(async () => { form.requestSubmit() })
        expect(createZevAccess).toHaveBeenCalledWith('z1', { party: 'p2', role: 'viewer', valid_to: null })
    })

    it('invites a contact as manager when chosen', async () => {
        const container = await render()
        const contact = rowOf(container, 'Verwaltung Nord')
        await act(async () => { button(contact, 'pages.zevSettings.access.invite').click() })
        const form = container.querySelector<HTMLFormElement>('.zev-access-form')!
        const select = levelSelect(form)
        await act(async () => {
            select.value = 'manager'
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await act(async () => { form.requestSubmit() })
        expect(createZevAccess).toHaveBeenCalledWith('z1', { party: 'c1', role: 'manager', valid_to: null })
    })

    it('lists a login given access by email, with its actions in the row menu', async () => {
        const container = await render()
        const books = rowOf(container, 'books@example.com')
        expect(books.textContent).toContain('pages.zevSettings.access.level.viewer')
        expect(books.querySelector('.badge-neutral, .badge-info')).toBeNull()
        // One quiet menu, no row of buttons.
        expect(books.querySelectorAll('button')).toHaveLength(1)
        await act(async () => { (await openMenu(books, 'pages.zevSettings.access.makeManager')).click() })
        expect(updateZevAccess).toHaveBeenCalledWith('z1', 'g9', { role: 'manager' })
        await act(async () => { (await openMenu(books, 'pages.zevSettings.access.revoke')).click() })
        expect(document.body.textContent).toContain('pages.zevSettings.access.revokeTitle')
    })

    it('reports an empty "Give access" form next to its field, not in a toast', async () => {
        const container = await render()
        await act(async () => { button(container.querySelector('.people-rows-header')!, 'pages.zevSettings.access.add').click() })
        const form = container.querySelector<HTMLFormElement>('.zev-access-form')!
        expect(form.querySelector('.zev-access-form-title')?.textContent).toBe('pages.zevSettings.access.formTitle')
        await act(async () => { form.requestSubmit() })
        const input = form.querySelector<HTMLInputElement>('input[type="email"]')!
        expect(input.getAttribute('aria-invalid')).toBe('true')
        expect(document.activeElement).toBe(input)
        expect(form.querySelector('.field-error')?.textContent).toBe('pages.zevSettings.access.emailRequired')
        expect(pushToast).not.toHaveBeenCalled()
        expect(createZevAccess).not.toHaveBeenCalled()
    })

    it('does not repeat a login that is the contact\'s own email', async () => {
        vi.mocked(fetchParties).mockResolvedValue([
            party('c2', 'Marco', { email: 'marco@example.com', accounts: [{ id: 11, email: 'marco@example.com', full_name: '', is_active: true }] }),
        ])
        vi.mocked(fetchPartyRoles).mockResolvedValue([])
        vi.mocked(fetchZevAccess).mockResolvedValue([entry('g11', user(11, 'marco@example.com'), { role: 'viewer' })])
        const container = await render()
        const row = rowOf(container, 'Marco')
        expect(row.textContent?.match(/marco@example\.com/g)).toHaveLength(1)
    })

    it('marks a pending invitation as a warning, with the resend in the menu', async () => {
        vi.mocked(fetchZevAccess).mockResolvedValue([
            entry('g9', { ...bookkeeper, pending_invitation: true }, { role: 'viewer' }),
        ])
        const container = await render()
        const books = rowOf(container, 'books@example.com')
        expect(books.querySelector('.issue-text--warning')?.textContent).toContain('pages.zevSettings.access.pending')
        expect(books.querySelector('.badge-warning')).toBeNull()
        await openMenu(books, 'pages.zevSettings.access.resend')
    })

    it('keeps delete in the row menu, only for a contact nobody depends on', async () => {
        vi.mocked(fetchParties).mockResolvedValue([party('c3', 'Hans', { email: 'hans@example.com' })])
        vi.mocked(fetchPartyRoles).mockResolvedValue([])
        vi.mocked(fetchZevAccess).mockResolvedValue([])
        const container = await render()
        const hans = rowOf(container, 'Hans')
        // Edit is an icon, not a labelled button; delete is quiet in the menu.
        expect(button(hans, 'common.edit') ?? hans.querySelector('button[aria-label="common.edit"]')).toBeTruthy()
        expect(hans.querySelector('button[aria-label="common.edit"]')!.textContent).toBe('')
        expect(button(hans, 'common.delete')).toBeUndefined()
        const item = await openMenu(hans, 'common.delete')
        expect(item.className).toContain('action-menu-item-danger')
    })

    it('gives a viewer no access controls', async () => {
        const container = await render(false)
        expect(rowOf(container, 'Lena').querySelectorAll('button')).toHaveLength(0)
        expect(rowOf(container, 'books@example.com').querySelectorAll('button')).toHaveLength(0)
    })
})
