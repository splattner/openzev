import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import type { Building, Party, ZevPartyRole } from '../src/types/api'

// ZEV settings → Parties (#761, SPEC-2026-10-zev-parties §8.3).

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
    createParty: vi.fn(),
    updateParty: vi.fn(),
    deleteParty: vi.fn(),
    assignPartyRole: vi.fn(),
    endPartyRole: vi.fn(),
    fetchZevAccess: vi.fn(() => Promise.resolve([])),
    fetchBuildings: vi.fn(() => Promise.resolve([])),
    setPartyRoleBuilding: vi.fn(),
}))

import { assignPartyRole, endPartyRole, fetchBuildings, fetchParties, fetchPartyRoles, setPartyRoleBuilding } from '../src/lib/api/zev'
import { ZevPartiesSection } from '../src/features/zev/ZevPartiesSection'
import { waitForCondition } from './helpers/waitForCondition'

const party = (id: string, name: string, over: Partial<Party> = {}): Party => ({
    id, zev: 'z1', kind: 'person', title: '', first_name: '', last_name: name, organisation_name: '', name_addition: '',
    email: '', phone: '', address_line1: '', address_line2: '', postal_code: '', city: '', notes: '',
    display_name: name, participations: [{ id: `p-${id}`, valid_from: '2026-01-01', valid_to: null }], roles: [], accounts: [],
    created_at: '', updated_at: '', ...over,
})
const role = (id: string, partyId: string, name: string, kind: ZevPartyRole['role'], validFrom: string, validTo: string | null = null): ZevPartyRole => ({
    id, zev: 'z1', party: partyId, party_display_name: name, role: kind, valid_from: validFrom, valid_to: validTo,
    created_at: '', updated_at: '',
})

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchParties).mockResolvedValue([
        party('a', 'Alt'),
        party('n', 'Neu'),
        party('v', 'Verwaltung Nord', {
            kind: 'organisation', organisation_name: 'Verwaltung Nord', participations: [],
            accounts: [{ id: 5, email: 'nord@example.com', full_name: '', is_active: true }],
        }),
    ])
    vi.mocked(fetchPartyRoles).mockResolvedValue([
        role('r1', 'a', 'Alt', 'issuer', '2025-01-01', '2026-03-31'),
        role('r2', 'n', 'Neu', 'issuer', '2026-04-01'),
        role('r3', 'a', 'Alt', 'landowner', '2025-01-01'),
    ])
    vi.mocked(assignPartyRole).mockResolvedValue(role('r9', 'a', 'Alt', 'representative', '2026-06-15'))
    vi.mocked(endPartyRole).mockResolvedValue(role('r3', 'a', 'Alt', 'landowner', '2025-01-01', '2026-06-15'))
})

async function render(canManage: boolean) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(
        createElement(MantineProvider, null,
            createElement(QueryClientProvider, { client }, createElement(ZevPartiesSection, { zevId: 'z1', canManage }))),
    ))
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
    return container
}

const buttons = (container: Element, label: string) =>
    Array.from(container.querySelectorAll('button')).filter((button) => button.textContent?.includes(label))

const landownerRow = (container: Element) => container.querySelector('.zev-role-list > li')!
const menuItem = (label: string) =>
    Array.from(document.querySelectorAll<HTMLElement>('[role="menuitem"]')).find((item) => item.textContent?.includes(label))
async function openMenu(row: Element, label: string) {
    await act(async () => row.querySelector<HTMLButtonElement>('button[aria-haspopup="menu"]')!.click())
    await waitForCondition(() => menuItem(label) !== undefined, `menu item ${label}`)
    return menuItem(label)!
}

async function click(element: Element) {
    await act(async () => { (element as HTMLElement).click() })
}

describe('ZevPartiesSection', () => {
    it('shows today\'s issuer, the missing representative, landowners and other contacts', async () => {
        const container = await render(true)
        const text = container.textContent ?? ''
        expect(text).toContain('Neu')
        expect(text).toContain('pages.zevSettings.parties.representativeNone')
        expect(text).toContain('Verwaltung Nord')
        // The earlier issuer is history, in a disclosure that starts closed.
        const history = container.querySelector<HTMLDetailsElement>('details.disclosure')!
        expect(history.open).toBe(false)
        expect(history.querySelector('summary')?.textContent).toBe('pages.zevSettings.parties.showHistory')
    })

    it('gives a viewer no actions', async () => {
        const container = await render(false)
        expect(container.textContent).toContain('Neu')
        expect(buttons(container, 'pages.zevSettings.parties.change.issuer')).toHaveLength(0)
        expect(buttons(container, 'pages.zevSettings.parties.addContact')).toHaveLength(0)
        expect(buttons(container, 'pages.zevSettings.parties.end')).toHaveLength(0)
    })

    it('sets a representative from a date', async () => {
        const container = await render(true)
        await click(buttons(container, 'pages.zevSettings.parties.set.representative')[0])
        const select = container.querySelector<HTMLSelectElement>('.zev-access-form select')!
        await act(async () => {
            select.value = 'v'
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await click(buttons(container, 'pages.zevSettings.parties.apply')[0])
        // A managing role is an access change: the dialog names the login first.
        expect(assignPartyRole).not.toHaveBeenCalled()
        expect(container.ownerDocument.body.textContent).toContain('pages.zevSettings.parties.grantsAccess:Verwaltung Nord')
        const confirmButton = Array.from(container.ownerDocument.querySelectorAll('button'))
            .filter((button) => button.textContent?.includes('pages.zevSettings.parties.apply'))
            .at(-1)!
        await click(confirmButton)
        expect(assignPartyRole).toHaveBeenCalledWith({ zev: 'z1', party: 'v', role: 'representative', valid_from: '2026-06-15' })
    })

    it('keeps ending a landowner in the row menu and the building next to it', async () => {
        vi.mocked(fetchBuildings).mockResolvedValue([{ id: 'b1', zev: 'z1', name: 'Haus A' } as Building])
        const container = await render(true)
        const row = landownerRow(container)
        // One visible action; the rare one is in the menu, not a second button.
        expect(buttons(row, 'pages.zevSettings.parties.setBuilding')).toHaveLength(1)
        expect(buttons(row, 'pages.zevSettings.parties.end')).toHaveLength(0)
        await openMenu(row, 'pages.zevSettings.parties.end')
    })

    it('asks before ending a landowner on a chosen day', async () => {
        const container = await render(true)
        const row = landownerRow(container)
        await act(async () => { (await openMenu(row, 'pages.zevSettings.parties.end')).click() })
        const form = container.querySelector<HTMLFormElement>('.zev-role-inline-form')!
        // Neutral, not a red destructive button.
        expect(form.querySelector('button[type="submit"]')!.className).toContain('button-secondary')
        await act(async () => { form.requestSubmit() })
        expect(endPartyRole).not.toHaveBeenCalled()
        expect(container.ownerDocument.body.textContent).toContain('pages.zevSettings.parties.endLandownerTitle')
        const confirmButton = Array.from(container.ownerDocument.querySelectorAll('button'))
            .filter((button) => button.textContent?.includes('pages.zevSettings.parties.end'))
            .at(-1)!
        await click(confirmButton)
        expect(endPartyRole).toHaveBeenCalledWith('r3', '2026-06-15')
    })

    it('saves a landowner\'s building only on Save', async () => {
        vi.mocked(fetchBuildings).mockResolvedValue([{ id: 'b1', zev: 'z1', name: 'Haus A' } as Building])
        const container = await render(true)
        await click(buttons(container, 'pages.zevSettings.parties.setBuilding')[0])
        const select = container.querySelector<HTMLSelectElement>('.zev-role-inline-form select')!
        await act(async () => {
            select.value = 'b1'
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        expect(setPartyRoleBuilding).not.toHaveBeenCalled()
        const form = select.closest('form')!
        await act(async () => { form.requestSubmit() })
        expect(setPartyRoleBuilding).toHaveBeenCalledWith('r3', 'b1')
    })

    it('reports a missing party next to the picker', async () => {
        const container = await render(true)
        await click(buttons(container, 'pages.zevSettings.parties.set.representative')[0])
        const form = container.querySelector<HTMLFormElement>('.zev-access-form')!
        expect(form.querySelector('.zev-access-form-title')?.textContent).toBe('pages.zevSettings.parties.set.representative')
        await act(async () => { form.requestSubmit() })
        const select = form.querySelector<HTMLSelectElement>('select')!
        expect(select.getAttribute('aria-invalid')).toBe('true')
        expect(form.querySelector('.field-error')?.textContent).toBe('pages.zevSettings.access.partyRequired')
        expect(assignPartyRole).not.toHaveBeenCalled()
    })

    it('shows a missing issuer as a problem with its fix beside it, not a banner', async () => {
        vi.mocked(fetchPartyRoles).mockResolvedValue([role('r3', 'a', 'Alt', 'landowner', '2025-01-01')])
        const container = await render(true)
        const issue = container.querySelector<HTMLElement>('.issue-text--warning')!
        expect(issue.textContent).toContain('pages.zevSettings.parties.issuerNone')
        expect(container.querySelector('.warning-banner')).toBeNull()
        await click(issue)
        expect(container.querySelector('.zev-access-form-title')?.textContent).toBe('pages.zevSettings.parties.set.issuer')
        // A viewer reads the same problem, without a way to act on it.
        const viewer = await render(false)
        expect(viewer.querySelector('.issue-text--warning')?.tagName).toBe('SPAN')
    })

    it('offers a retry when the people cannot be loaded', async () => {
        vi.mocked(fetchParties).mockRejectedValue(new Error('down'))
        const container = await render(true)
        expect(container.textContent).toContain('common.error')
        expect(container.querySelector('p.error-banner')).toBeNull()
        expect(container.querySelector('button')).not.toBeNull()
    })

    it('shows an empty state with its actions when nobody else is listed', async () => {
        vi.mocked(fetchParties).mockResolvedValue([party('a', 'Alt'), party('n', 'Neu')])
        const container = await render(true)
        expect(container.querySelector('.empty-state')?.textContent).toContain('pages.zevSettings.parties.noContacts')
        expect(buttons(container, 'pages.zevSettings.parties.addContact')).toHaveLength(1)
        expect(buttons(container, 'pages.zevSettings.access.add')).toHaveLength(1)
        const viewer = await render(false)
        expect(viewer.querySelector('.empty-state button')).toBeNull()
    })
})
